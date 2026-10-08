from flask import (
    Flask, render_template, request, redirect, session, url_for,
    send_from_directory, abort
)
from PIL import Image, UnidentifiedImageError
import secrets
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


def obter_token_voto():
    if "voto_token" not in session:
        session["voto_token"] = secrets.token_urlsafe(32)
    return session["voto_token"]


@app.route("/")
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


@app.route("/nova")
def nova():
    return render_template("nova.html")


@app.route("/salvar", methods=["POST"])
def salvar():
    titulo = request.form["titulo"]
    descricao = request.form["descricao"]
    categoria = request.form["categoria"]
    local = request.form["local"]

    imagem, erro = salvar_imagem(request.files.get("imagem"))
    if erro:
        return render_template("nova.html", erro=erro), 400

    model.inserir(titulo, descricao, categoria, local, imagem)
    return redirect("/")


@app.route("/imagem/<nome>")
def imagem(nome):
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

    reclamacoes = model.listar()
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
