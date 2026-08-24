"""
Aplica as migrations SQL (V1, V2, ...) no banco apontado por DATABASE_URL.

Uso:
    set DATABASE_URL=postgresql://usuario:senha@host:porta/banco
    python run_migrations.py

Não depende do cliente psql -- usa psycopg2 (já listado no requirements.txt).
Roda cada arquivo migrations/V*.sql em ordem alfabética, dentro de uma
transação por arquivo. Se um arquivo já tiver sido aplicado e for rodado de
novo, os erros de "já existe" do Postgres não são silenciados de propósito --
é melhor você ver o erro do que a migration falhar pela metade silenciosamente.
"""
import os
import sys
import glob

import psycopg2

DATABASE_URL = os.environ.get("DATABASE_URL", "")

if not DATABASE_URL:
    print("ERRO: variável de ambiente DATABASE_URL não definida.")
    print('Defina com: set DATABASE_URL=postgresql://usuario:senha@host:porta/banco')
    sys.exit(1)

migrations_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "migrations")
arquivos = sorted(glob.glob(os.path.join(migrations_dir, "V*.sql")))

if not arquivos:
    print(f"Nenhum arquivo de migration encontrado em {migrations_dir}")
    sys.exit(1)

conn = psycopg2.connect(DATABASE_URL)
conn.autocommit = False

try:
    for caminho in arquivos:
        nome = os.path.basename(caminho)
        print(f"Aplicando {nome} ...")
        with open(caminho, "r", encoding="utf-8") as f:
            sql = f.read()
        with conn.cursor() as cur:
            cur.execute(sql)
        conn.commit()
        print(f"  -> OK")
    print("Todas as migrations foram aplicadas com sucesso.")
finally:
    conn.close()
