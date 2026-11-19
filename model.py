import os
import unicodedata
import psycopg2
import psycopg2.extras
from psycopg2 import sql
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

# Pasta das fotos anexadas (fica FORA de static/ e é servida pela rota /imagem).
PASTA_UPLOADS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "uploads")
os.makedirs(PASTA_UPLOADS, exist_ok=True)


def criar_banco():
    # No Neon, o banco de dados (neondb) já existe por padrão.
    pass


def conectar():
    if not DATABASE_URL:
        raise RuntimeError("A variável DATABASE_URL não foi encontrada no arquivo .env.")
    return psycopg2.connect(DATABASE_URL)


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
            downvotes INTEGER NOT NULL DEFAULT 0,
            imagem VARCHAR(64)
        )
    """)

    # Usuários do sistema (login geral). Só o painel administrativo
    # consegue relacionar uma reclamação ao seu autor.
    cur.execute("""
        CREATE TABLE IF NOT EXISTS usuario(
            id SERIAL PRIMARY KEY,
            matricula VARCHAR(30) UNIQUE NOT NULL,
            nome VARCHAR(100) NOT NULL,
            senha_hash VARCHAR(255) NOT NULL
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
    # Nome do arquivo da foto (opcional, no máximo uma por reclamação).
    cur.execute("""
        ALTER TABLE reclamacao
        ADD COLUMN IF NOT EXISTS imagem VARCHAR(64)
    """)

    # Autor da reclamação (visível apenas no painel administrativo).
    cur.execute("""
        ALTER TABLE reclamacao
        ADD COLUMN IF NOT EXISTS usuario_id INTEGER
        REFERENCES usuario(id) ON DELETE SET NULL
    """)

    # Guarda o token de quem já votou em cada reclamação,
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


def criar_usuario(matricula, nome, senha_hash):
    """Retorna True se criou, False se a matrícula já existe."""
    conn = conectar()
    cur = conn.cursor()
    try:
        cur.execute("""
            INSERT INTO usuario (matricula, nome, senha_hash)
            VALUES (%s, %s, %s)
        """, (matricula, nome, senha_hash))
        conn.commit()
        return True
    except psycopg2.errors.UniqueViolation:
        conn.rollback()
        return False
    finally:
        cur.close()
        conn.close()


def buscar_usuario(matricula):
    conn = conectar()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT * FROM usuario WHERE matricula = %s", (matricula,))
    usuario = cur.fetchone()
    cur.close()
    conn.close()
    return usuario


def inserir(titulo, descricao, categoria, local, imagem=None, usuario_id=None):
    conn = conectar()
    cur = conn.cursor()

    categoria_id = _obter_ou_criar_categoria(cur, categoria)
    local_id = _obter_ou_criar_local(cur, local)

    cur.execute("""
        INSERT INTO reclamacao
        (titulo, descricao, categoria_id, local_id, imagem, usuario_id)
        VALUES (%s, %s, %s, %s, %s, %s)
    """, (
        titulo,
        descricao,
        categoria_id,
        local_id,
        imagem,
        usuario_id
    ))

    conn.commit()
    cur.close()
    conn.close()


# Formas de ordenar a lista. As chaves vêm da URL (?ordenar=...), mas só os
# valores abaixo (texto fixo, escrito aqui) entram no SQL, então não há risco
# de SQL injection.
ORDENACOES = {
    # Relevância: upvotes ganham mais peso quando chegam em menos tempo.
    # nota = upvotes / (horas desde a criação + 2) ^ 1,5
    # Com a mesma quantidade de upvotes, a reclamação mais nova fica na frente.
    # Reclamações sem upvotes empatam em 0 e são ordenadas da mais nova para a mais antiga.
    "relevancia": """
        r.upvotes::float / POWER(
            GREATEST(
                EXTRACT(EPOCH FROM (CURRENT_TIMESTAMP - r.data_criacao)) / 3600.0,
                0
            )::float + 2,
            1.5
        ) DESC,
        r.id DESC
    """,
    # Mais votados: maior saldo (upvotes - downvotes) primeiro.
    "votos": "(r.upvotes - r.downvotes) DESC, r.upvotes DESC, r.id DESC",
    # Mais recentes: as postadas há menos tempo primeiro.
    "recentes": "r.data_criacao DESC, r.id DESC",
}

ORDENACAO_PADRAO = "relevancia"

# Pesquisa sem diferenciar maiúsculas/minúsculas nem acentos
# ("iluminacao" encontra "Iluminação"). Feito com translate(), sem precisar
# instalar nenhuma extensão no PostgreSQL.
_COM_ACENTO = "áàâãäéèêëíìîïóòôõöúùûüçÁÀÂÃÄÉÈÊËÍÌÎÏÓÒÔÕÖÚÙÛÜÇ"
_SEM_ACENTO = "aaaaaeeeeiiiiooooouuuuc" * 2
assert len(_COM_ACENTO) == len(_SEM_ACENTO)

# Campos onde a pesquisa procura (o protocolo, ex.: 0004, é tratado à parte).
_CAMPOS_BUSCA = ("r.titulo", "r.descricao", "l.nome_local")


def _normalizar(texto):
    """Minúsculas e sem acentos, para comparar com o texto do banco."""
    decomposto = unicodedata.normalize("NFKD", texto)
    sem_acento = "".join(c for c in decomposto if not unicodedata.combining(c))
    return sem_acento.lower()


def _condicao_busca(busca):
    """
    Monta a condição SQL da pesquisa. Cada palavra digitada precisa aparecer
    em pelo menos um dos campos (título, descrição, local ou protocolo).
    Retorna (sql, parametros), ou (None, []) se não houver nada para buscar.
    """
    palavras = _normalizar(busca).split()[:8]
    if not palavras:
        return None, []

    por_palavra = []
    parametros = []

    for palavra in palavras:
        # Escapa % _ ! para que sejam tratados como texto comum no LIKE.
        for c in ("!", "%", "_"):
            palavra = palavra.replace(c, "!" + c)
        padrao = f"%{palavra}%"

        partes = [
            f"lower(translate({campo}, '{_COM_ACENTO}', '{_SEM_ACENTO}')) LIKE %s ESCAPE '!'"
            for campo in _CAMPOS_BUSCA
        ]
        partes.append("LPAD(r.id::text, 4, '0') LIKE %s ESCAPE '!'")

        por_palavra.append("(" + " OR ".join(partes) + ")")
        parametros.extend([padrao] * len(partes))

    return " AND ".join(por_palavra), parametros


def listar(categoria=None, ordenar="recentes", busca=None, com_autor=False):
    # com_autor=True só deve ser usado no painel administrativo.
    # A listagem pública nunca consulta a tabela de usuários.
    if ordenar not in ORDENACOES:
        ordenar = ORDENACAO_PADRAO

    conn = conectar()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    condicoes = []
    parametros = []

    if categoria and categoria != "Todas":
        condicoes.append("c.nom_categoria = %s")
        parametros.append(categoria)

    if busca:
        condicao, params_busca = _condicao_busca(busca)
        if condicao:
            condicoes.append(condicao)
            parametros.extend(params_busca)

    filtro = ("WHERE " + " AND ".join(condicoes)) if condicoes else ""

    colunas_autor = ""
    join_autor = ""
    if com_autor:
        colunas_autor = ", u.nome AS autor_nome, u.matricula AS autor_matricula"
        join_autor = "LEFT JOIN usuario u ON r.usuario_id = u.id"

    cur.execute(f"""
        SELECT
            r.id,
            r.titulo,
            r.descricao,
            r.data_criacao,
            r.status,
            r.upvotes,
            r.downvotes,
            r.imagem,
            c.nom_categoria AS categoria,
            l.nome_local AS local
            {colunas_autor}
        FROM reclamacao r
        JOIN categoria c ON r.categoria_id = c.id
        JOIN local l ON r.local_id = l.id
        {join_autor}
        {filtro}
        ORDER BY {ORDENACOES[ordenar]}
    """, tuple(parametros))

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

    # Busca o nome da foto antes de apagar a linha.
    cur.execute("SELECT imagem FROM reclamacao WHERE id = %s", (id,))
    linha = cur.fetchone()

    cur.execute("""
        DELETE FROM reclamacao
        WHERE id = %s
    """, (id,))

    conn.commit()
    cur.close()
    conn.close()

    # Remove o arquivo do disco (se existir).
    if linha and linha[0]:
        try:
            os.remove(os.path.join(PASTA_UPLOADS, linha[0]))
        except FileNotFoundError:
            pass
        