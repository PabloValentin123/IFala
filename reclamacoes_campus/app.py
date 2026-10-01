from flask import Flask, render_template, request, redirect, session, url_for
import secrets
import model

app = Flask(__name__)
app.secret_key = "IFALA-SECRET-KEY-TROQUE-EM-PRODUCAO"

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
    reclamacoes = model.listar(categoria)
    categorias = model.listar_categorias()

    return render_template(
        "index.html",
        reclamacoes=reclamacoes,
        categorias=categorias,
        categoria_selecionada=categoria
    )


@app.route("/nova")
def nova():
    return render_template("nova.html")


@app.route("/salvar", methods=["POST"])
def salvar():
    titulo = request.form["titulo"]
    descricao = request.form["descricao"]
    categoria = request.form["categoria"]
    local = request.form["local"]

    model.inserir(titulo, descricao, categoria, local)
    return redirect("/")


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
