
import psycopg2.extras
from psycopg2 import sql

HOST = "localhost"
PORT = "5432"
DB_NAME = "campus"
USER = "postgres"
PASSWORD = "postgres"


def criar_banco():
    conn = psycopg2.connect(
        host=HOST,
        port=PORT,
        dbname="postgres",
        user=USER,
        password=PASSWORD
    )
    conn.autocommit = True
    cur = conn.cursor()

    cur.execute(
        "SELECT 1 FROM pg_database WHERE datname = %s",
        (DB_NAME,)
    )

    if cur.fetchone() is None:
        cur.execute(
            sql.SQL("CREATE DATABASE {}").format(
                sql.Identifier(DB_NAME)
            )
        )

    cur.close()
    conn.close()


def conectar():
    return psycopg2.connect(
        host=HOST,
        port=PORT,
        dbname=DB_NAME,
        user=USER,
        password=PASSWORD
    )


def criar_tabelas():
    conn = conectar()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS categoria(
            id SERIAL PRIMARY KEY,
            nom_categoria VARCHAR(50) UNIQUE NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS local(
            id SERIAL PRIMARY KEY,
            nome_local VARCHAR(100) UNIQUE NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS reclamacao(
            id SERIAL PRIMARY KEY,
            titulo VARCHAR(100) NOT NULL,
            descricao TEXT NOT NULL,
            data_criacao TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            status VARCHAR(30) NOT NULL DEFAULT 'Aberta',
            categoria_id INTEGER NOT NULL REFERENCES categoria(id),
            local_id INTEGER NOT NULL REFERENCES local(id),
            upvotes INTEGER NOT NULL DEFAULT 0,
            downvotes INTEGER NOT NULL DEFAULT 0
        )
    """)

    # Compatibilidade com bancos já criados antes desta versão.
    cur.execute("""
        ALTER TABLE reclamacao
        ADD COLUMN IF NOT EXISTS upvotes INTEGER NOT NULL DEFAULT 0
    """)
    cur.execute("""
        ALTER TABLE reclamacao
        ADD COLUMN IF NOT EXISTS downvotes INTEGER NOT NULL DEFAULT 0
    """)

    # Guarda a sessão anônima que já votou em cada reclamação,
    # evitando múltiplos votos iguais na mesma sessão.
    cur.execute("""
        CREATE TABLE IF NOT EXISTS voto(
            id SERIAL PRIMARY KEY,
            reclamacao_id INTEGER NOT NULL REFERENCES reclamacao(id) ON DELETE CASCADE,
            token VARCHAR(128) NOT NULL,
            tipo VARCHAR(10) NOT NULL CHECK (tipo IN ('upvote', 'downvote')),
            UNIQUE(reclamacao_id, token)
        )
    """)

    conn.commit()
    cur.close()
    conn.close()


def _obter_ou_criar_categoria(cur, nome):
    cur.execute(
        "SELECT id FROM categoria WHERE nom_categoria = %s",
        (nome,)
    )
    linha = cur.fetchone()

    if linha:
        return linha[0]

    cur.execute(
        "INSERT INTO categoria (nom_categoria) VALUES (%s) RETURNING id",
        (nome,)
    )
    return cur.fetchone()[0]


def _obter_ou_criar_local(cur, nome):
    cur.execute(
        "SELECT id FROM local WHERE nome_local = %s",
        (nome,)
    )
    linha = cur.fetchone()

    if linha:
        return linha[0]

    cur.execute(
        "INSERT INTO local (nome_local) VALUES (%s) RETURNING id",
        (nome,)
    )
    return cur.fetchone()[0]


def inserir(titulo, descricao, categoria, local):
    conn = conectar()
    cur = conn.cursor()

    categoria_id = _obter_ou_criar_categoria(cur, categoria)
    local_id = _obter_ou_criar_local(cur, local)

    local_id = _obter_ou_criar_local(cur, local)

    cur.execute("""
        INSERT INTO reclamacao
        (titulo, descricao, categoria_id, local_id)
        VALUES (%s, %s, %s, %s)
    """, (
        titulo,
        descricao,
        categoria_id,
        local_id
    ))

    conn.commit()
    cur.close()
    conn.close()


def listar(categoria=None):
    conn = conectar()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    if categoria and categoria != "Todas":
        cur.execute("""
            SELECT
                r.id,
                r.titulo,
                r.descricao,
                r.data_criacao,
                r.status,
                r.upvotes,
                r.downvotes,
                c.nom_categoria AS categoria,
                l.nome_local AS local
            FROM reclamacao r
            JOIN categoria c ON r.categoria_id = c.id
            JOIN local l ON r.local_id = l.id
            WHERE c.nom_categoria = %s
            ORDER BY r.id DESC
        """, (categoria,))
    else:
        cur.execute("""
            SELECT
                r.id,
                r.titulo,
                r.descricao,
                r.data_criacao,
                r.status,
                r.upvotes,
                r.downvotes,
                c.nom_categoria AS categoria,
                l.nome_local AS local
            FROM reclamacao r
            JOIN categoria c ON r.categoria_id = c.id
            JOIN local l ON r.local_id = l.id
            ORDER BY r.id DESC
        """)

    dados = cur.fetchall()
    cur.close()
    conn.close()
    return dados


def listar_categorias():
    conn = conectar()
    cur = conn.cursor()

    cur.execute("""
        SELECT nom_categoria
        FROM categoria
        ORDER BY nom_categoria
    """)

    categorias = [linha[0] for linha in cur.fetchall()]
    cur.close()
    conn.close()
    return categorias


def votar(reclamacao_id, token, tipo):
    if tipo not in ("upvote", "downvote"):
        return "invalido"

    conn = conectar()
    cur = conn.cursor()

    cur.execute("""
        SELECT tipo
        FROM voto
        WHERE reclamacao_id = %s AND token = %s
    """, (reclamacao_id, token))

    voto_existente = cur.fetchone()

    if voto_existente:
        # Clicar no mesmo botão novamente remove o voto.
        if voto_existente[0] == tipo:
            cur.execute("""
                DELETE FROM voto
                WHERE reclamacao_id = %s AND token = %s
            """, (reclamacao_id, token))

            coluna = "upvotes" if tipo == "upvote" else "downvotes"
            cur.execute(
                sql.SQL("UPDATE reclamacao SET {} = GREATEST({} - 1, 0) WHERE id = %s")
                .format(sql.Identifier(coluna), sql.Identifier(coluna)),
                (reclamacao_id,)
            )
            resultado = "removido"
        else:
            # Troca o voto.
            antigo = voto_existente[0]
            cur.execute("""
                UPDATE voto
                SET tipo = %s
                WHERE reclamacao_id = %s AND token = %s
            """, (tipo, reclamacao_id, token))

            coluna_antiga = "upvotes" if antigo == "upvote" else "downvotes"
            coluna_nova = "upvotes" if tipo == "upvote" else "downvotes"

            cur.execute(
                sql.SQL("UPDATE reclamacao SET {} = GREATEST({} - 1, 0) WHERE id = %s")
                .format(sql.Identifier(coluna_antiga), sql.Identifier(coluna_antiga)),
                (reclamacao_id,)
            )
            cur.execute(
                sql.SQL("UPDATE reclamacao SET {} = {} + 1 WHERE id = %s")
                .format(sql.Identifier(coluna_nova), sql.Identifier(coluna_nova)),
                (reclamacao_id,)
            )
            resultado = "trocado"
    else:
        cur.execute("""
            INSERT INTO voto (reclamacao_id, token, tipo)
            VALUES (%s, %s, %s)
        """, (reclamacao_id, token, tipo))

        coluna = "upvotes" if tipo == "upvote" else "downvotes"
        cur.execute(
            sql.SQL("UPDATE reclamacao SET {} = {} + 1 WHERE id = %s")
            .format(sql.Identifier(coluna), sql.Identifier(coluna)),
            (reclamacao_id,)
        )
        resultado = "adicionado"

    conn.commit()
    cur.close()
    conn.close()
    return resultado


def atualizar_status(id, status):
    conn = conectar()
    cur = conn.cursor()

    cur.execute("""
        UPDATE reclamacao
        SET status = %s
        WHERE id = %s
    """, (status, id))

    conn.commit()
    cur.close()
    conn.close()


def excluir(id):
    conn = conectar()
    cur = conn.cursor()

    cur.execute("""
        DELETE FROM reclamacao
        WHERE id = %s
    """, (id,))

    conn.commit()
    cur.close()
    conn.close()
