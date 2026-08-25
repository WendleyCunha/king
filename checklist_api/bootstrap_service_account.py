"""
Cria a conta de serviço fixa que o mod_checklist.py (Painel Streamlit) usa
para autenticar na API de Checklist, sem depender de login individual por
usuário do Painel — os dois sistemas de usuário (Firestore x Postgres) são
independentes, e essa é a forma mais simples de conectar os dois por agora.

Roda UMA VEZ SÓ. Se o e-mail já existir, o script avisa e não faz nada
(seguro rodar de novo por engano).

Uso (no CMD, dentro da pasta checklist_api, com o venv ativo):
    set DATABASE_URL=postgresql://...   (External Database URL do Render)
    set JWT_SECRET=qualquer-coisa       (só precisa existir; não precisa ser
                                          o mesmo da API rodando no Render)
    python bootstrap_service_account.py

Pede o e-mail e a senha da conta de serviço interativamente — a senha não
aparece na tela enquanto você digita (getpass). Guarde essas duas
informações nos Secrets do Streamlit depois (é o que o mod_checklist.py lê).
"""
import os
import sys
import getpass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from modules import SessionLocal, Usuario, Perfil, UsuarioEscopo, hash_password

# Todas as permissões que existem hoje na API (ver require_permission(...)
# nos routers) — a conta de serviço tem acesso amplo, com escopo global
# (unidade_id/setor_id = None), já que é usada pelo Painel administrativo.
PERMISSOES_SERVICO = [
    "aplicacao.criar", "aplicacao.executar", "aplicacao.visualizar",
    "checklist.criar", "checklist.publicar", "checklist.visualizar",
    "dashboard.visualizar",
    "plano_acao.criar", "plano_acao.gerenciar", "plano_acao.visualizar",
    "relatorio.exportar",
    "unidade.gerenciar", "unidade.visualizar",
    "usuario.gerenciar", "usuario.visualizar",
]


def main():
    print("=== Criação da conta de serviço — Painel KingStar ↔ API de Checklist ===\n")
    email = input("E-mail da conta de serviço (ex: painel-checklist@kingstarcolchoes.com.br): ").strip()
    senha = getpass.getpass("Senha da conta de serviço (não aparece na tela): ").strip()

    if not email or not senha:
        print("\nE-mail e senha são obrigatórios. Nada foi criado.")
        return

    if len(senha.encode("utf-8")) > 72:
        print("\nSenha muito longa (limite do bcrypt é 72 bytes). Escolha uma senha mais curta.")
        return

    db = SessionLocal()
    try:
        existente = db.query(Usuario).filter(Usuario.email == email).first()
        if existente:
            print(f"\nJá existe um usuário com o e-mail '{email}'. Nada foi alterado.")
            print("Se quiser trocar a senha dessa conta, me avise que criamos uma função própria pra isso.")
            return

        usuario = Usuario(
            nome="Painel KingStar (Conta de Serviço)",
            email=email,
            senha_hash=hash_password(senha),
            status="ativo",
        )
        db.add(usuario)
        db.flush()  # garante usuario.id preenchido antes de criar o vínculo

        perfil = Perfil(
            nome="Serviço — Painel KingStar",
            permissoes=PERMISSOES_SERVICO,
        )
        db.add(perfil)
        db.flush()

        vinculo = UsuarioEscopo(
            usuario_id=usuario.id,
            perfil_id=perfil.id,
            unidade_id=None,  # None = escopo global (toda a organização)
            setor_id=None,
        )
        db.add(vinculo)

        db.commit()
        print(f"\n✅ Conta de serviço '{email}' criada com sucesso — acesso global, todas as permissões.")
        print("Guarde o e-mail e a senha nos Secrets do Streamlit (CHECKLIST_API_EMAIL / CHECKLIST_API_SENHA).")
    except Exception as e:
        db.rollback()
        print(f"\n❌ Erro ao criar a conta de serviço: {e}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
