from db import get_db, agora_iso, proximo_numero

COL_CARGOS = "cargos"          # doc id = nome do cargo
COL_FUNCIONARIOS = "funcionarios"
COL_VENDEDORES = "vendedores"  # doc id = código do vendedor
COL_VENDAS_PEDIDOS = "pedidos"
COL_REGRAS = "regras_comissao"


def cadastrar_cargo(nome: str, is_vendedor: bool = False, descricao: str = "") -> dict:
    ref = get_db().collection(COL_CARGOS).document(nome)
    if ref.get().exists:
        raise ValueError("Já existe um cargo com esse nome.")
    cargo = {"nome": nome, "is_vendedor": is_vendedor, "descricao": descricao}
    ref.set(cargo)
    return cargo


def listar_cargos() -> list:
    return [d.to_dict() for d in get_db().collection(COL_CARGOS).stream()]


def cadastrar_funcionario(nome: str, cpf: str, cargo_nome: str, salario: float,
                           data_admissao: str = None) -> dict:
    """
    Se o CARGO estiver marcado como is_vendedor=True, gera automaticamente
    um CÓDIGO DE VENDEDOR (VEND-0001...) — diferente do login do
    colaborador — usado só pra apuração de comissão.
    """
    db = get_db()
    cargo_doc = db.collection(COL_CARGOS).document(cargo_nome).get()
    if not cargo_doc.exists:
        raise ValueError("Cargo não encontrado.")
    cargo = cargo_doc.to_dict()

    existentes = list(db.collection(COL_FUNCIONARIOS).where("cpf", "==", cpf).stream())
    if existentes:
        raise ValueError("Já existe funcionário com esse CPF.")

    ref = db.collection(COL_FUNCIONARIOS).document()
    funcionario = {
        "id": ref.id, "nome": nome, "cpf": cpf, "cargo": cargo_nome, "salario": salario,
        "data_admissao": data_admissao or agora_iso(), "ativo": True, "vendedor_codigo": None,
    }

    if cargo.get("is_vendedor"):
        codigo = proximo_numero("vendedores", "VEND", largura=4)
        db.collection(COL_VENDEDORES).document(codigo).set({
            "codigo": codigo, "funcionario_id": ref.id, "ativo": True,
        })
        funcionario["vendedor_codigo"] = codigo

    ref.set(funcionario)
    return funcionario


def listar_funcionarios(apenas_ativos=True) -> list:
    docs = get_db().collection(COL_FUNCIONARIOS).stream()
    out = [d.to_dict() for d in docs]
    if apenas_ativos:
        out = [f for f in out if f.get("ativo", True)]
    return sorted(out, key=lambda f: f.get("nome", ""))


def listar_vendedores(apenas_ativos=True) -> list:
    docs = get_db().collection(COL_VENDEDORES).stream()
    out = [d.to_dict() for d in docs]
    if apenas_ativos:
        out = [v for v in out if v.get("ativo", True)]
    return out


def calcular_comissao_vendedor(vendedor_codigo: str) -> dict:
    """
    Comissão em tempo real, aplicando todas as regras ativas cadastradas
    pela ABA DIRETORIA (INDIVIDUAL / LOJA / REDE — nesta versão "rede" usa
    a mesma base da loja, já que o sistema cobre uma única unidade).
    """
    db = get_db()
    vend_doc = db.collection(COL_VENDEDORES).document(vendedor_codigo).get()
    if not vend_doc.exists:
        raise ValueError("Código de vendedor não encontrado.")

    pedidos_vendedor = db.collection(COL_VENDAS_PEDIDOS).where("vendedor_codigo", "==", vendedor_codigo).stream()
    total_individual = sum(p.to_dict()["valor"] for p in pedidos_vendedor)
    # NOTA DE CUSTO: total_loja soma TODOS os pedidos (usado só quando existir
    # regra LOJA/REDE ativa) — em volume alto, vale manter um contador
    # agregado à parte em vez de escanear a coleção inteira a cada consulta.
    total_loja = sum(p.to_dict()["valor"] for p in db.collection(COL_VENDAS_PEDIDOS).stream())

    regras = [r.to_dict() for r in db.collection(COL_REGRAS).where("ativo", "==", True).stream()]
    detalhe = []
    comissao_total = 0.0
    for regra in regras:
        base = {"INDIVIDUAL": total_individual, "LOJA": total_loja, "REDE": total_loja}[regra["tipo"]]
        valor_regra = base * (regra["percentual"] / 100)
        comissao_total += valor_regra
        detalhe.append({"tipo": regra["tipo"], "percentual": regra["percentual"], "base": base, "valor": valor_regra})

    return {
        "vendedor_codigo": vendedor_codigo, "total_vendas_individual": total_individual,
        "comissao_total": comissao_total, "detalhe": detalhe,
    }
