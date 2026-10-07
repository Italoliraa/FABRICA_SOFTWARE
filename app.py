"""
BarberFlow - Sistema de agendamento para barbearias.
100% Python (Flask + SQLite), renderizacao no servidor, sem JavaScript.
Atende aos requisitos RF01 a RF18.
"""
from datetime import datetime
from functools import wraps

from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    session,
    flash,
    abort,
)

from db import (
    init_db,
    get_db,
    hash_senha,
    horarios_disponiveis,
    slots_do_dia,
)

app = Flask(__name__)
app.secret_key = "barberflow-chave-secreta-troque-em-producao"

init_db()


# ----------------------------------------------------------------------------
# Helpers de autenticacao e autorizacao
# ----------------------------------------------------------------------------
def usuario_atual():
    uid = session.get("usuario_id")
    if not uid:
        return None
    conn = get_db()
    u = conn.execute("SELECT * FROM usuarios WHERE id=?", (uid,)).fetchone()
    conn.close()
    return u


def login_obrigatorio(*papeis):
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            u = usuario_atual()
            if not u:
                flash("Faca login para continuar.", "erro")
                return redirect(url_for("login"))
            if papeis and u["papel"] not in papeis:
                abort(403)
            return f(*args, **kwargs)

        return wrapper

    return decorator


@app.context_processor
def injeta_usuario():
    return {"usuario": usuario_atual()}


@app.template_filter("moeda")
def moeda(valor):
    return f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


@app.template_filter("data_br")
def data_br(iso):
    try:
        return datetime.strptime(iso, "%Y-%m-%d").strftime("%d/%m/%Y")
    except (ValueError, TypeError):
        return iso


STATUS_LABEL = {
    "agendado": "Agendado",
    "em_atendimento": "Em atendimento",
    "concluido": "Concluido",
    "cancelado": "Cancelado",
}


@app.template_filter("status_label")
def status_label(s):
    return STATUS_LABEL.get(s, s)


# ----------------------------------------------------------------------------
# Rotas publicas / autenticacao
# ----------------------------------------------------------------------------
@app.route("/")
def index():
    conn = get_db()
    servicos = conn.execute("SELECT * FROM servicos ORDER BY nome").fetchall()
    barbeiros = conn.execute(
        "SELECT * FROM barbeiros WHERE ativo=1 ORDER BY nome"
    ).fetchall()
    conn.close()
    return render_template("index.html", servicos=servicos, barbeiros=barbeiros)


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        senha = request.form.get("senha", "")
        conn = get_db()
        u = conn.execute(
            "SELECT * FROM usuarios WHERE email=?", (email,)
        ).fetchone()
        conn.close()
        if u and u["senha"] == hash_senha(senha):
            session["usuario_id"] = u["id"]
            flash(f"Bem-vindo, {u['nome']}!", "sucesso")
            if u["papel"] == "admin":
                return redirect(url_for("admin_agendamentos"))
            if u["papel"] == "barbeiro":
                return redirect(url_for("barbeiro_agenda"))
            return redirect(url_for("cliente_agendamentos"))
        flash("E-mail ou senha invalidos.", "erro")
    return render_template("login.html")


@app.route("/cadastro")
def cadastro():
    """Cadastro de clientes desativado; redireciona para o login."""
    flash("O cadastro de clientes foi desativado. Use uma conta existente.", "erro")
    return redirect(url_for("login"))


@app.route("/logout")
def logout():
    session.clear()
    flash("Voce saiu da conta.", "sucesso")
    return redirect(url_for("index"))


# ----------------------------------------------------------------------------
# AREA DO CLIENTE (RF04 a RF10)
# ----------------------------------------------------------------------------
@app.route("/agendar", methods=["GET", "POST"])
@login_obrigatorio("cliente")
def cliente_novo_agendamento():
    conn = get_db()
    servicos = conn.execute("SELECT * FROM servicos ORDER BY nome").fetchall()
    barbeiros = conn.execute(
        "SELECT * FROM barbeiros WHERE ativo=1 ORDER BY nome"
    ).fetchall()

    hoje = datetime.now().strftime("%Y-%m-%d")

    # Valores selecionados (podem vir de GET pre-selecao ou do POST)
    servico_id = request.values.get("servico_id", type=int)
    barbeiro_id = request.values.get("barbeiro_id", type=int)
    data = request.values.get("data", hoje)
    horarios = []
    if barbeiro_id and data:
        horarios = horarios_disponiveis(barbeiro_id, data)

    if request.method == "POST" and request.form.get("acao") == "confirmar":
        hora = request.form.get("hora", "")
        if not (servico_id and barbeiro_id and data and hora):
            flash("Selecione servico, barbeiro, data e horario.", "erro")
        else:
            # RF08 - impede conflito de horario (dupla verificacao no servidor)
            conflito = conn.execute(
                "SELECT 1 FROM agendamentos WHERE barbeiro_id=? AND data=? AND hora=? AND status!='cancelado'",
                (barbeiro_id, data, hora),
            ).fetchone()
            if conflito:
                flash("Esse horario acabou de ser ocupado. Escolha outro.", "erro")
                horarios = horarios_disponiveis(barbeiro_id, data)
            else:
                conn.execute(
                    """INSERT INTO agendamentos
                       (cliente_id, barbeiro_id, servico_id, data, hora, status, criado_em)
                       VALUES (?,?,?,?,?, 'agendado', ?)""",
                    (
                        session["usuario_id"],
                        barbeiro_id,
                        servico_id,
                        data,
                        hora,
                        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),  # RF17
                    ),
                )
                conn.commit()
                conn.close()
                flash("Agendamento confirmado!", "sucesso")
                return redirect(url_for("cliente_agendamentos"))

    conn.close()
    return render_template(
        "cliente_agendar.html",
        servicos=servicos,
        barbeiros=barbeiros,
        horarios=horarios,
        servico_id=servico_id,
        barbeiro_id=barbeiro_id,
        data=data,
        hoje=hoje,
    )


@app.route("/meus-agendamentos")
@login_obrigatorio("cliente")
def cliente_agendamentos():
    conn = get_db()
    ags = conn.execute(
        """SELECT a.*, s.nome AS servico_nome, s.preco, s.duracao_min,
                  b.nome AS barbeiro_nome
           FROM agendamentos a
           JOIN servicos s ON s.id = a.servico_id
           JOIN barbeiros b ON b.id = a.barbeiro_id
           WHERE a.cliente_id=?
           ORDER BY a.data DESC, a.hora DESC""",
        (session["usuario_id"],),
    ).fetchall()
    conn.close()
    return render_template("cliente_agendamentos.html", agendamentos=ags)


@app.route("/cancelar/<int:ag_id>", methods=["POST"])
@login_obrigatorio("cliente")
def cliente_cancelar(ag_id):
    conn = get_db()
    ag = conn.execute(
        "SELECT * FROM agendamentos WHERE id=? AND cliente_id=?",
        (ag_id, session["usuario_id"]),
    ).fetchone()
    if not ag:
        conn.close()
        abort(404)
    if ag["status"] in ("concluido", "cancelado"):
        flash("Este agendamento nao pode ser cancelado.", "erro")
    else:
        conn.execute(
            "UPDATE agendamentos SET status='cancelado' WHERE id=?", (ag_id,)
        )
        conn.commit()
        flash("Agendamento cancelado.", "sucesso")
    conn.close()
    return redirect(url_for("cliente_agendamentos"))


# ----------------------------------------------------------------------------
# AREA DO BARBEIRO (RF11 a RF13)
# ----------------------------------------------------------------------------
def barbeiro_do_usuario(usuario_id):
    conn = get_db()
    b = conn.execute(
        "SELECT * FROM barbeiros WHERE usuario_id=?", (usuario_id,)
    ).fetchone()
    conn.close()
    return b


@app.route("/agenda")
@login_obrigatorio("barbeiro")
def barbeiro_agenda():
    b = barbeiro_do_usuario(session["usuario_id"])
    if not b:
        flash("Seu perfil de barbeiro ainda nao foi configurado.", "erro")
        return redirect(url_for("index"))
    filtro_data = request.args.get("data", "")
    conn = get_db()
    query = """SELECT a.*, s.nome AS servico_nome, s.preco, s.duracao_min,
                      u.nome AS cliente_nome, u.telefone AS cliente_telefone
               FROM agendamentos a
               JOIN servicos s ON s.id = a.servico_id
               JOIN usuarios u ON u.id = a.cliente_id
               WHERE a.barbeiro_id=?"""
    params = [b["id"]]
    if filtro_data:
        query += " AND a.data=?"
        params.append(filtro_data)
    query += " ORDER BY a.data, a.hora"
    ags = conn.execute(query, params).fetchall()
    conn.close()
    return render_template(
        "barbeiro_agenda.html", agendamentos=ags, barbeiro=b, filtro_data=filtro_data
    )


@app.route("/atendimento/<int:ag_id>/status", methods=["POST"])
@login_obrigatorio("barbeiro")
def barbeiro_status(ag_id):
    b = barbeiro_do_usuario(session["usuario_id"])
    novo = request.form.get("status", "")
    if novo not in ("agendado", "em_atendimento", "concluido", "cancelado"):
        abort(400)
    conn = get_db()
    ag = conn.execute(
        "SELECT * FROM agendamentos WHERE id=? AND barbeiro_id=?", (ag_id, b["id"])
    ).fetchone()
    if not ag:
        conn.close()
        abort(404)
    conn.execute("UPDATE agendamentos SET status=? WHERE id=?", (novo, ag_id))
    conn.commit()
    conn.close()
    flash("Status atualizado.", "sucesso")
    return redirect(url_for("barbeiro_agenda", data=request.form.get("data", "")))


# ----------------------------------------------------------------------------
# AREA DO ADMINISTRADOR (RF14 a RF16)
# ----------------------------------------------------------------------------
@app.route("/admin/agendamentos")
@login_obrigatorio("admin")
def admin_agendamentos():
    status = request.args.get("status", "")
    conn = get_db()
    query = """SELECT a.*, s.nome AS servico_nome, s.preco,
                      b.nome AS barbeiro_nome, u.nome AS cliente_nome
               FROM agendamentos a
               JOIN servicos s ON s.id = a.servico_id
               JOIN barbeiros b ON b.id = a.barbeiro_id
               JOIN usuarios u ON u.id = a.cliente_id"""
    params = []
    if status:
        query += " WHERE a.status=?"
        params.append(status)
    query += " ORDER BY a.data DESC, a.hora DESC"
    ags = conn.execute(query, params).fetchall()
    conn.close()
    return render_template("admin_agendamentos.html", agendamentos=ags, status=status)


# ---- CRUD de servicos (RF02, RF03, RF14) ----
@app.route("/admin/servicos")
@login_obrigatorio("admin")
def admin_servicos():
    conn = get_db()
    servicos = conn.execute("SELECT * FROM servicos ORDER BY nome").fetchall()
    conn.close()
    return render_template("admin_servicos.html", servicos=servicos)


@app.route("/admin/servicos/salvar", methods=["POST"])
@login_obrigatorio("admin")
def admin_servico_salvar():
    sid = request.form.get("id", type=int)
    nome = request.form.get("nome", "").strip()
    descricao = request.form.get("descricao", "").strip()
    duracao = request.form.get("duracao_min", type=int)
    preco = request.form.get("preco", type=float)
    if not (nome and duracao and preco is not None):
        flash("Preencha nome, duracao e preco.", "erro")
        return redirect(url_for("admin_servicos"))
    conn = get_db()
    if sid:
        conn.execute(
            "UPDATE servicos SET nome=?, descricao=?, duracao_min=?, preco=? WHERE id=?",
            (nome, descricao, duracao, preco, sid),
        )
        flash("Servico atualizado.", "sucesso")
    else:
        conn.execute(
            "INSERT INTO servicos (nome, descricao, duracao_min, preco) VALUES (?,?,?,?)",
            (nome, descricao, duracao, preco),
        )
        flash("Servico cadastrado.", "sucesso")
    conn.commit()
    conn.close()
    return redirect(url_for("admin_servicos"))


@app.route("/admin/servicos/excluir/<int:sid>", methods=["POST"])
@login_obrigatorio("admin")
def admin_servico_excluir(sid):
    conn = get_db()
    conn.execute("DELETE FROM servicos WHERE id=?", (sid,))
    conn.commit()
    conn.close()
    flash("Servico excluido.", "sucesso")
    return redirect(url_for("admin_servicos"))


# ---- CRUD de barbeiros (RF01, RF15) ----
@app.route("/admin/barbeiros")
@login_obrigatorio("admin")
def admin_barbeiros():
    conn = get_db()
    barbeiros = conn.execute(
        """SELECT b.*, u.email FROM barbeiros b
           LEFT JOIN usuarios u ON u.id = b.usuario_id
           ORDER BY b.nome"""
    ).fetchall()
    conn.close()
    return render_template("admin_barbeiros.html", barbeiros=barbeiros)


@app.route("/admin/barbeiros/salvar", methods=["POST"])
@login_obrigatorio("admin")
def admin_barbeiro_salvar():
    bid = request.form.get("id", type=int)
    nome = request.form.get("nome", "").strip()
    especialidade = request.form.get("especialidade", "").strip()
    email = request.form.get("email", "").strip().lower()
    senha = request.form.get("senha", "")
    ativo = 1 if request.form.get("ativo") == "on" else 0

    if not nome:
        flash("Informe o nome do barbeiro.", "erro")
        return redirect(url_for("admin_barbeiros"))

    conn = get_db()
    if bid:  # edicao
        b = conn.execute("SELECT * FROM barbeiros WHERE id=?", (bid,)).fetchone()
        conn.execute(
            "UPDATE barbeiros SET nome=?, especialidade=?, ativo=? WHERE id=?",
            (nome, especialidade, ativo, bid),
        )
        if b and b["usuario_id"] and email:
            conn.execute(
                "UPDATE usuarios SET nome=?, email=? WHERE id=?",
                (nome, email, b["usuario_id"]),
            )
            if senha:
                conn.execute(
                    "UPDATE usuarios SET senha=? WHERE id=?",
                    (hash_senha(senha), b["usuario_id"]),
                )
        flash("Barbeiro atualizado.", "sucesso")
    else:  # novo barbeiro (cria login se e-mail informado)
        usuario_id = None
        if email:
            existe = conn.execute(
                "SELECT 1 FROM usuarios WHERE email=?", (email,)
            ).fetchone()
            if existe:
                conn.close()
                flash("Ja existe um usuario com este e-mail.", "erro")
                return redirect(url_for("admin_barbeiros"))
            conn.execute(
                "INSERT INTO usuarios (nome, email, senha, papel) VALUES (?,?,?,'barbeiro')",
                (nome, email, hash_senha(senha or "barbeiro123")),
            )
            usuario_id = conn.execute(
                "SELECT id FROM usuarios WHERE email=?", (email,)
            ).fetchone()["id"]
        conn.execute(
            "INSERT INTO barbeiros (usuario_id, nome, especialidade, ativo) VALUES (?,?,?,?)",
            (usuario_id, nome, especialidade, ativo),
        )
        flash("Barbeiro cadastrado.", "sucesso")
    conn.commit()
    conn.close()
    return redirect(url_for("admin_barbeiros"))


@app.route("/admin/barbeiros/excluir/<int:bid>", methods=["POST"])
@login_obrigatorio("admin")
def admin_barbeiro_excluir(bid):
    conn = get_db()
    b = conn.execute("SELECT * FROM barbeiros WHERE id=?", (bid,)).fetchone()
    if b:
        conn.execute("DELETE FROM barbeiros WHERE id=?", (bid,))
        if b["usuario_id"]:
            conn.execute("DELETE FROM usuarios WHERE id=?", (b["usuario_id"],))
        conn.commit()
    conn.close()
    flash("Barbeiro excluido.", "sucesso")
    return redirect(url_for("admin_barbeiros"))


@app.errorhandler(403)
def erro_403(e):
    return render_template("erro.html", codigo=403, mensagem="Acesso nao autorizado."), 403


@app.errorhandler(404)
def erro_404(e):
    return render_template("erro.html", codigo=404, mensagem="Pagina nao encontrada."), 404


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=3000, debug=True)
