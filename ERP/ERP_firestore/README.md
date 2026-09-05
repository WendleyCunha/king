# ERP — KingStar / Lila Closet (versão Firestore)

Segue exatamente as convenções que vocês já usam no Painel KingStar
(`auth_db.py`): Firestore como banco, `get_db()` cacheado em
`st.session_state`, hash de senha simples (sha256), normalização de
login, `@st.cache_data` com `.clear()` em toda escrita, e `batch`/
`transaction` do Firestore pra manter várias coleções consistentes numa
única operação.

> Existe também uma versão anterior deste mesmo ERP usando
> SQLAlchemy + SQLite/Postgres (pasta `ERP/`), construída antes de vocês
> decidirem seguir o padrão Firestore. Ela ficou pronta e testada, mas
> **esta pasta (Firestore) é a versão atual pra usar**. Pode apagar a
> outra se não for precisar.

## Setup

1. `pip install -r requirements.txt`
2. Crie `.streamlit/secrets.toml` com a mesma chave de service account que
   o painel já usa:
   ```toml
   textkey = '''{ ... json da service account ... }'''
   ```
3. (opcional, recomendado) Se quiser um banco Firestore separado do
   painel — pra não misturar coleções — troque `database="erp"` em
   `db.py` pelo nome do banco que você criar no console do Firebase.
   Se preferir usar o mesmo banco `"portal"` do painel, é só trocar essa
   linha.
4. `streamlit run app.py`
5. Login padrão: `admin` / `admin123` (acesso EDITAR em todas as abas,
   igual ao admin master do painel — hardcoded no `auth.py`, não fica no
   banco). Crie os demais usuários pela própria ABA DIRETORIA.

## Por que não consegui testar contra o Firestore de verdade

O sandbox onde eu rodo só tem acesso de rede a alguns domínios (GitHub,
PyPI, npm) — `googleapis.com` não está liberado, então não consigo
conectar nem num Firestore real nem num emulador daqui. Validei:

- Sintaxe de todos os arquivos (`py_compile`) ✅
- A versão anterior (SQLAlchemy) rodou um teste de ponta a ponta completo
  simulando todo o fluxo de negócio (venda sem estoque → bloqueio →
  entrada → liberação → agendamento → carga → motorista → travamento →
  faturamento → comissão → eliminação de pedido) e todas as regras
  bateram certo — a lógica desta versão Firestore é a mesma, só a forma
  de persistir mudou.

**Recomendo rodar um teste manual real** assim que configurar as
`secrets`: cadastre um cliente, um produto, faça uma venda sem estoque
(deve nascer BLOQUEADO), dê entrada no estoque (deve liberar
automaticamente) e siga o fluxo até faturar. Qualquer erro de índice do
Firestore aparece com um link pronto pra criar o índice em 1 clique —
é normal precisar criar 1 ou 2 na primeira vez que uma tela for aberta
(estão sinalizados nos comentários do código, ex: `produtos+status+criado_em`
em `services/produto_service.py`).

## Modelagem (coleções)

| Coleção | ID do documento | Observação |
|---|---|---|
| `usuarios` | login (normalizado) | mesma coleção pra gente de escritório E motoristas (campo `is_motorista` + `placa`), igual ao painel |
| `clientes` | auto | |
| `produtos` | SKU | |
| `movimentos_estoque` | auto | histórico de entrada/saída/ajuste/devolução |
| `pedidos` | número sequencial (`PED-000001`) | **cada pedido = 1 item único** (regra do negócio); guarda dados da venda embutidos (cliente, produto, valor) em vez de uma coleção `vendas` separada, pra evitar joins |
| `cargas` | auto | lista de números de pedido dentro dela |
| `notas_fiscais` | número sequencial (`NF-000001`) | PDF de controle interno — **não é NF-e válida na SEFAZ**, isso exige um provedor homologado (Focus NFe, eNotas, TecnoSpeed); o ponto de integração está isolado em `services/fiscal_service.py` |
| `cargos` | nome do cargo | `is_vendedor` decide se gera código de vendedor |
| `funcionarios` | auto | |
| `vendedores` | código sequencial (`VEND-0001`) | separado do login do usuário, só pra apuração de comissão |
| `regras_comissao` | auto | INDIVIDUAL / LOJA / REDE |
| `lancamentos_financeiros` | auto | espelha cada venda |
| `notificacoes` | auto | ex: pedido retirado de carga avisa DIRETORIA/RH/AGENDAR |
| `empresa` | doc fixo `config` | dados usados na nota fiscal |
| `contadores` | nome do contador | usado com `transaction` pra gerar números sequenciais sem colisão |

Não existe uma coleção `encomendas` separada: a fila de compras da ABA
ENCOMENDAR é derivada dos próprios `pedidos` com `status == "BLOQUEADO"`
(ver `services/encomenda_service.py`) — evita manter duas fontes da
mesma informação sincronizadas.

## Integração com o outro sistema via API

Como pediram pra manter tudo no mesmo lugar quando possível: hoje as
telas chamam as funções de `services/` diretamente (sem API). Se algum
dia o outro sistema precisar ler/escrever dados daqui, dá pra expor um
FastAPI fino por cima dessas mesmas funções de `services/` (mesmo padrão
do Painel KingStar: Streamlit + FastAPI no Render) sem duplicar regra de
negócio — a função do serviço continua sendo a única fonte da lógica.
