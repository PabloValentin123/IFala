from flask import (
    Flask, render_template, request, redirect, session, url_for,
    send_from_directory, abort
)
from PIL import Image, UnidentifiedImageError
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
import hashlib
import uuid
import os
import model

app = Flask(__name__)
app.secret_key = "IFALA-SECRET-KEY-TROQUE-EM-PRODUCAO"

# Limite do corpo da requisição (a foto enviada pode ter no máximo 5 MB).
LIMITE_MB = 5
app.config["MAX_CONTENT_LENGTH"] = LIMITE_MB * 1024 * 1024
FORMATOS_ACEITOS = {"JPEG", "PNG", "WEBP"}

# Opções do menu "Ordenar por" da página inicial: (chave na URL, texto exibido)
OPCOES_ORDENACAO = [
    ("relevancia", "Relevância"),
    ("votos", "Mais votados"),
    ("recentes", "Mais recentes"),
]

# Credenciais simples para o projeto acadêmico.
# Em produção, use variáveis de ambiente e senhas com hash.
ADMIN_USUARIO = "admin"
ADMIN_SENHA = "1234"

model.criar_banco()
model.criar_tabelas()


def usuario_logado(f):
    """Exige login de usuário comum para acessar a rota."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("usuario_id"):
            return redirect(url_for("entrar"))
        return f(*args, **kwargs)
    return wrapper


def obter_token_voto():
    # Token derivado do usuário logado: garante um voto por pessoa e evita
    # gravar o id do usuário diretamente na tabela de votos.
    base = f"{app.secret_key}:{session['usuario_id']}"
    return hashlib.sha256(base.encode()).hexdigest()


@app.route("/entrar", methods=["GET", "POST"])
def entrar():
    erro = None

    if request.method == "POST":
        matricula = request.form.get("matricula", "").strip()
        senha = request.form.get("senha", "")

        usuario = model.buscar_usuario(matricula)
        if usuario and check_password_hash(usuario["senha_hash"], senha):
            session["usuario_id"] = usuario["id"]
            return redirect(url_for("index"))

        erro = "Matrícula ou senha incorretas."

    return render_template("entrar.html", erro=erro)


@app.route("/cadastro", methods=["GET", "POST"])
def cadastro():
    erro = None

    if request.method == "POST":
        nome = request.form.get("nome", "").strip()[:100]
        matricula = request.form.get("matricula", "").strip()[:30]
        senha = request.form.get("senha", "")

        if not nome or not matricula:
            erro = "Preencha nome e matrícula."
        elif len(senha) < 6:
            erro = "A senha precisa ter pelo menos 6 caracteres."
        elif not model.criar_usuario(matricula, nome, generate_password_hash(senha)):
            erro = "Essa matrícula já está cadastrada."
        else:
            return redirect(url_for("entrar"))

    return render_template("cadastro.html", erro=erro)


@app.route("/sair")
def sair():
    session.pop("usuario_id", None)
    return redirect(url_for("entrar"))


@app.route("/")
@usuario_logado
def index():
    categoria = request.args.get("categoria", "Todas")

    # Ordenação: relevancia (padrão), votos ou recentes.
    ordenar = request.args.get("ordenar", model.ORDENACAO_PADRAO)
    if ordenar not in model.ORDENACOES:
        ordenar = model.ORDENACAO_PADRAO

    # Pesquisa por texto (?q=...)
    busca = request.args.get("q", "").strip()[:100]

    reclamacoes = model.listar(categoria, ordenar, busca)
    categorias = model.listar_categorias()

    return render_template(
        "index.html",
        reclamacoes=reclamacoes,
        categorias=categorias,
        categoria_selecionada=categoria,
        ordenar_selecionado=ordenar,
        opcoes_ordenacao=OPCOES_ORDENACAO,
        busca=busca
    )


def salvar_imagem(arquivo):
    """
    Valida e salva a foto enviada.

    Retorna (nome_do_arquivo, erro):
      - (None, None)   -> nenhuma foto enviada (campo é opcional)
      - (nome, None)   -> foto salva com sucesso
      - (None, "msg")  -> foto inválida
    """
    if arquivo is None or not arquivo.filename:
        return None, None

    try:
        # verify() confere se o arquivo é mesmo uma imagem;
        # depois é preciso abrir de novo para poder processá-la.
        img = Image.open(arquivo)
        formato = img.format
        img.verify()
        arquivo.seek(0)
        img = Image.open(arquivo)
        img.load()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        return None, "O arquivo enviado não é uma imagem válida."

    if formato not in FORMATOS_ACEITOS:
        return None, "Formato não aceito. Envie uma imagem JPG, PNG ou WebP."

    # Regrava a imagem do zero como JPEG: isso descarta EXIF (GPS, modelo do
    # celular, data), preservando o anonimato de quem enviou.
    img = img.convert("RGB")
    img.thumbnail((1600, 1600))

    nome = uuid.uuid4().hex + ".jpg"  # nome gerado pelo servidor
    img.save(os.path.join(model.PASTA_UPLOADS, nome), "JPEG", quality=80)
    return nome, None


@app.route("/chamado")
@usuario_logado
def chamado():
    # Página com o passo a passo para casos mais sérios (canal oficial: Fala.BR)
    return render_template("chamado.html")


@app.route("/nova")
@usuario_logado
def nova():
    return render_template("nova.html")


@app.route("/salvar", methods=["POST"])
@usuario_logado
def salvar():
    titulo = request.form["titulo"]
    descricao = request.form["descricao"]
    categoria = request.form["categoria"]
    local = request.form["local"]

    imagem, erro = salvar_imagem(request.files.get("imagem"))
    if erro:
        return render_template("nova.html", erro=erro), 400

    model.inserir(titulo, descricao, categoria, local, imagem,
                  usuario_id=session["usuario_id"])
    return redirect("/")


@app.route("/imagem/<nome>")
def imagem(nome):
    # Sem @usuario_logado de propósito: o painel admin usa esta rota também.
    if not (session.get("usuario_id") or session.get("admin_logado")):
        abort(404)
    # Só serve arquivos gerados pelo sistema (uuid hex + .jpg).
    if not nome.endswith(".jpg") or not nome[:-4].isalnum():
        abort(404)
    return send_from_directory(model.PASTA_UPLOADS, nome)


@app.errorhandler(413)
def arquivo_grande(_erro):
    return render_template(
        "nova.html",
        erro=f"A foto é muito grande. O limite é {LIMITE_MB} MB."
    ), 413


@app.route("/votar/<int:id>/<tipo>", methods=["POST"])
@usuario_logado
def votar(id, tipo):
    if tipo not in ("upvote", "downvote"):
        return redirect("/")

    model.votar(id, obter_token_voto(), tipo)

    destino = request.form.get("next") or request.referrer or url_for("index")
    return redirect(destino)


@app.route("/login", methods=["GET", "POST"])
def login():
    erro = None

    if request.method == "POST":
        usuario = request.form.get("usuario", "").strip()
        senha = request.form.get("senha", "")

        if usuario == ADMIN_USUARIO and senha == ADMIN_SENHA:
            session["admin_logado"] = True
            return redirect(url_for("admin"))

        erro = "Usuário ou senha incorretos."

    return render_template("login.html", erro=erro)


@app.route("/logout")
def logout():
    session.pop("admin_logado", None)
    return redirect(url_for("index"))


@app.route("/admin")
def admin():
    if not session.get("admin_logado"):
        return redirect(url_for("login"))

    reclamacoes = model.listar(com_autor=True)
    return render_template(
        "admin.html",
        reclamacoes=reclamacoes
    )


@app.route("/status/<int:id>", methods=["POST"])
def status(id):
    if not session.get("admin_logado"):
        return redirect(url_for("login"))

    novo_status = request.form["status"]
    model.atualizar_status(id, novo_status)
    return redirect("/admin")


@app.route("/excluir/<int:id>")
def excluir(id):
    if not session.get("admin_logado"):
        return redirect(url_for("login"))

    model.excluir(id)
    return redirect("/admin")


if __name__ == "__main__":
    app.run(debug=True)
