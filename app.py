
import csv
import io
import math
import os
import re
import secrets
import sqlite3
from datetime import date, datetime, timedelta
from functools import wraps
from urllib.parse import parse_qs, urlsplit

from flask import (
    Flask,
    Response,
    abort,
    flash,
    render_template,
    request,
    redirect,
    url_for,
    session,
    stream_with_context,
)

from flask_socketio import SocketIO
from flask_wtf.csrf import CSRFProtect

from db import (
    init_db,
    get_db,
    hash_senha,
    senha_forte,
    verificar_senha,
    DIAS_SEMANA,
    horarios_disponiveis,
    horarios_disponiveis_por_duracao,
    obter_disponibilidade_semana,
    salvar_disponibilidade,
    slots_do_dia,
)

app = Flask(__name__)
APP_ENV = os.environ.get("APP_ENV", "development").strip().lower()
if APP_ENV not in {"development", "production"}:
    raise RuntimeError("APP_ENV deve ser 'development' ou 'production'.")

secret_key = os.environ.get("BARBERAGENDA_SECRET_KEY", "").strip()
if not secret_key:
    if APP_ENV == "production":
        raise RuntimeError(
            "BARBERAGENDA_SECRET_KEY é obrigatório em produção e deve ter "
            "pelo menos 32 caracteres."
        )
    secret_key = secrets.token_urlsafe(32)
elif len(secret_key) < 32:
    raise RuntimeError("BARBERAGENDA_SECRET_KEY deve ter pelo menos 32 caracteres.")

app.config.update(
    SECRET_KEY=secret_key,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=APP_ENV == "production",
)

socketio = SocketIO(app, async_mode="threading")
CSRFProtect(app)

init_db()

def notificar_barbeiros():
    conn = get_db()

    barbeiros = conn.execute(
        """
        SELECT id, nome
        FROM barbeiros
        WHERE ativo = 1
        ORDER BY nome
        """
    ).fetchall()

    conn.close()

    dados = [
        {
            "id": b["id"],
            "nome": b["nome"]
        }
        for b in barbeiros
    ]

    socketio.emit(
        "barbeiros_atualizados",
        {"barbeiros": dados}
    )


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


def turnos_do_expediente(expediente):
    if not expediente:
        return []

    turnos = []
    if expediente["hora_inicio"] < "12:00":
        turnos.append("manhã")
    if expediente["hora_fim"] > "12:00":
        turnos.append("tarde")
    return turnos


def proxima_pagina_agendamento(valor):
    if not valor:
        return None

    try:
        destino = urlsplit(valor)
    except ValueError:
        return None

    if destino.scheme or destino.netloc or destino.path != url_for(
        "cliente_novo_agendamento"
    ):
        return None

    parametros = parse_qs(destino.query)
    if set(parametros) - {"servico_id", "barbeiro_id", "data", "hora"}:
        return None

    servico_ids = parametros.get("servico_id", [])
    if (
        len(servico_ids) != 1
        or len(servico_ids[0]) > 19
        or not servico_ids[0].isascii()
        or not servico_ids[0].isdigit()
    ):
        return None

    servico_id = int(servico_ids[0])
    if servico_id < 1:
        return None

    argumentos = {"servico_id": servico_id}
    barbeiro_ids = parametros.get("barbeiro_id", [])
    if barbeiro_ids:
        if (
            len(barbeiro_ids) != 1
            or len(barbeiro_ids[0]) > 19
            or not barbeiro_ids[0].isascii()
            or not barbeiro_ids[0].isdigit()
            or int(barbeiro_ids[0]) < 1
        ):
            return None
        argumentos["barbeiro_id"] = int(barbeiro_ids[0])

    datas = parametros.get("data", [])
    if datas:
        if len(datas) != 1:
            return None
        try:
            datetime.strptime(datas[0], "%Y-%m-%d")
        except ValueError:
            return None
        argumentos["data"] = datas[0]

    horas = parametros.get("hora", [])
    if horas:
        if (
            len(horas) != 1
            or not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", horas[0])
            or "barbeiro_id" not in argumentos
            or "data" not in argumentos
        ):
            return None
        argumentos["hora"] = horas[0]

    return url_for("cliente_novo_agendamento", **argumentos)


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
    next_url = proxima_pagina_agendamento(request.values.get("next", ""))
    usuario = usuario_atual()
    if usuario:
        if usuario["papel"] == "cliente" and next_url:
            return redirect(next_url)
        if usuario["papel"] == "admin":
            return redirect(url_for("admin_dashboard"))
        if usuario["papel"] == "barbeiro":
            return redirect(url_for("barbeiro_agenda"))
        return redirect(url_for("cliente_agendamentos"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        senha = request.form.get("senha", "")
        conn = get_db()
        u = conn.execute(
            "SELECT * FROM usuarios WHERE email=?", (email,)
        ).fetchone()
        senha_valida, rehash = (
            verificar_senha(u["senha"], senha) if u else (False, False)
        )
        if senha_valida and rehash:
            conn.execute(
                "UPDATE usuarios SET senha=? WHERE id=?",
                (hash_senha(senha), u["id"]),
            )
            conn.commit()
        conn.close()
        if senha_valida:
            session.clear()
            session["usuario_id"] = u["id"]
            flash(f"Bem-vindo, {u['nome']}!", "sucesso")
            if u["papel"] == "cliente" and next_url:
                return redirect(next_url)
            if u["papel"] == "admin":
                return redirect(url_for("admin_dashboard"))
            if u["papel"] == "barbeiro":
                return redirect(url_for("barbeiro_agenda"))
            return redirect(url_for("cliente_agendamentos"))
        flash("E-mail ou senha invalidos.", "erro")
    return render_template("login.html", next_url=next_url)


@app.route("/cadastro", methods=["GET", "POST"])
def cadastro():
    next_url = proxima_pagina_agendamento(request.values.get("next", ""))
    usuario = usuario_atual()
    if usuario:
        if usuario["papel"] == "cliente" and next_url:
            return redirect(next_url)
        if usuario["papel"] == "admin":
            return redirect(url_for("admin_dashboard"))
        if usuario["papel"] == "barbeiro":
            return redirect(url_for("barbeiro_agenda"))
        return redirect(url_for("cliente_agendamentos"))

    if request.method == "GET":
        return render_template("cadastro.html", next_url=next_url)

    nome = request.form.get("nome", "").strip()
    email = request.form.get("email", "").strip().lower()
    telefone = request.form.get("telefone", "").strip()
    digitos_telefone = re.sub(r"\D", "", telefone)
    senha = request.form.get("senha", "")

    if not nome or len(nome) > 120 or not re.fullmatch(
        r"[^@\s]+@[^@\s]+\.[^@\s]+", email
    ):
        flash("Informe seu nome e um e-mail valido.", "erro")
        return render_template("cadastro.html", next_url=next_url)
    if len(telefone) > 25 or not 10 <= len(digitos_telefone) <= 15:
        flash("Informe um numero de celular valido com DDD.", "erro")
        return render_template("cadastro.html", next_url=next_url)
    if not senha_forte(senha):
        flash("A senha deve ter entre 12 e 128 caracteres.", "erro")
        return render_template("cadastro.html", next_url=next_url)

    conn = get_db()
    try:
        cursor = conn.execute(
            """INSERT INTO usuarios (nome, email, senha, papel, telefone)
               VALUES (?, ?, ?, 'cliente', ?)""",
            (nome, email, hash_senha(senha), telefone),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        conn.rollback()
        flash("Ja existe uma conta com este e-mail.", "erro")
        return render_template("cadastro.html", next_url=next_url)
    finally:
        conn.close()

    session.clear()
    session["usuario_id"] = cursor.lastrowid
    flash(f"Conta criada. Bem-vindo, {nome}!", "sucesso")
    if next_url:
        return redirect(next_url)
    return redirect(url_for("cliente_agendamentos"))


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    flash("Voce saiu da conta.", "sucesso")
    return redirect(url_for("index"))


# ----------------------------------------------------------------------------
# AREA DO CLIENTE 
# ----------------------------------------------------------------------------
@app.route("/barbeiros")
@login_obrigatorio("cliente")
def cliente_barbeiros():
    hoje = datetime.now().strftime("%Y-%m-%d")
    data = request.args.get("data", hoje)
    try:
        data_consulta = datetime.strptime(data, "%Y-%m-%d")
    except ValueError:
        flash("Informe uma data valida para consultar a disponibilidade.", "erro")
        data = hoje
        data_consulta = datetime.strptime(hoje, "%Y-%m-%d")

    conn = get_db()
    barbeiros = conn.execute(
        "SELECT * FROM barbeiros WHERE ativo=1 ORDER BY nome"
    ).fetchall()
    servicos = conn.execute("SELECT * FROM servicos ORDER BY nome").fetchall()

    barbeiro_selecionado = request.args.get("barbeiro_id", type=int)
    if request.args.get("toggle_data") == data:
        barbeiro_selecionado = None
    horarios = []
    servicos_por_horario = {}
    expediente = None
    turnos_expediente = []
    dias_atendimento = []

    for barbeiro in barbeiros:
        disponibilidade = obter_disponibilidade_semana(barbeiro["id"])
        if barbeiro["id"] == barbeiro_selecionado:
            expediente = next(
                (
                    item
                    for item in disponibilidade
                    if item["dia_semana"] == data_consulta.weekday()
                ),
                None,
            )
            turnos_expediente = turnos_do_expediente(expediente)
            dias_atendimento = [
                nome for dia, nome in DIAS_SEMANA
                if any(item["dia_semana"] == dia for item in disponibilidade)
            ]
            if expediente and servicos:
                horarios_por_duracao = horarios_disponiveis_por_duracao(
                    barbeiro["id"],
                    data,
                    {servico["duracao_min"] for servico in servicos},
                    conn=conn,
                )
                horarios = sorted(
                    {
                        horario
                        for horarios_servico in horarios_por_duracao.values()
                        for horario in horarios_servico
                    }
                )
                servicos_por_horario = {
                    horario: [
                        str(servico["id"])
                        for servico in servicos
                        if horario in horarios_por_duracao.get(
                            servico["duracao_min"], []
                        )
                    ]
                    for horario in horarios
                }

    if barbeiro_selecionado and not any(
        barbeiro["id"] == barbeiro_selecionado for barbeiro in barbeiros
    ):
        barbeiro_selecionado = None

    conn.close()
    return render_template(
        "cliente_barbeiros.html",
        barbeiros=barbeiros,
        servicos=servicos,
        barbeiro_selecionado=barbeiro_selecionado,
        data=data,
        hoje=hoje,
        expediente=expediente,
        turnos_expediente=turnos_expediente,
        dias_atendimento=dias_atendimento,
        horarios=horarios,
        servicos_por_horario=servicos_por_horario,
    )


@app.route("/agendar", methods=["GET", "POST"])
def cliente_novo_agendamento():
    usuario = usuario_atual()
    if usuario and usuario["papel"] != "cliente":
        abort(403)

    confirmar = request.method == "POST" and request.form.get("acao") == "confirmar"
    if confirmar and not usuario:
        flash("Entre ou crie sua conta para confirmar o agendamento.", "erro")
        argumentos = {
            "servico_id": request.form.get("servico_id", type=int),
            "barbeiro_id": request.form.get("barbeiro_id", type=int),
            "data": request.form.get("data", ""),
            "hora": request.form.get("hora", ""),
        }
        proxima_pagina = proxima_pagina_agendamento(
            url_for(
                "cliente_novo_agendamento",
                **{chave: valor for chave, valor in argumentos.items() if valor},
            )
        )
        if proxima_pagina:
            return redirect(url_for("login", next=proxima_pagina))
        return redirect(url_for("login"))

    conn = get_db()
    if confirmar:
        conn.execute("BEGIN IMMEDIATE")

    servicos = conn.execute("SELECT * FROM servicos ORDER BY nome").fetchall()
    barbeiros = conn.execute(
        "SELECT * FROM barbeiros WHERE ativo=1 ORDER BY nome"
    ).fetchall()

    hoje = datetime.now().strftime("%Y-%m-%d")

    # Valores selecionados (podem vir de GET pre-selecao ou do POST)
    servico_id = request.values.get("servico_id", type=int)
    servico_selecionado = next(
        (servico for servico in servicos if servico["id"] == servico_id),
        None,
    )
    barbeiro_id = request.values.get("barbeiro_id", type=int)
    data = request.values.get("data", hoje)
    horarios = []
    expediente = None
    turnos_expediente = []
    dias_atendimento = []
    if barbeiro_id and data:
        try:
            dia_semana = datetime.strptime(data, "%Y-%m-%d").weekday()
        except ValueError:
            flash("Informe uma data valida para consultar a disponibilidade.", "erro")
        else:
            disponibilidade = obter_disponibilidade_semana(barbeiro_id)
            expediente = next(
                (item for item in disponibilidade if item["dia_semana"] == dia_semana),
                None,
            )
            turnos_expediente = turnos_do_expediente(expediente)
            dias_atendimento = [
                nome for dia, nome in DIAS_SEMANA
                if any(item["dia_semana"] == dia for item in disponibilidade)
            ]
            horarios = horarios_disponiveis(
                barbeiro_id,
                data,
                servico_selecionado["duracao_min"] if servico_selecionado else None,
                conn=conn,
            )
    hora_selecionada = request.values.get("hora", "")
    if hora_selecionada not in horarios:
        hora_selecionada = ""

    if request.method == "POST" and request.form.get("acao") == "confirmar":
        hora = request.form.get("hora", "")
        if not (servico_id and barbeiro_id and data and hora):
            flash("Selecione servico, barbeiro, data e horario.", "erro")
        elif not any(servico["id"] == servico_id for servico in servicos):
            flash("Selecione um servico valido.", "erro")
        elif hora not in horarios:
            if not expediente:
                flash(
                    "Esse barbeiro nao atende nesse dia. "
                    f"Dias de atendimento: {', '.join(dias_atendimento)}.",
                    "erro",
                )
            elif horarios:
                flash(
                    "Esse horario nao esta disponivel. "
                    f"Horarios disponiveis: {', '.join(horarios)}.",
                    "erro",
                )
            else:
                flash("Nao ha horarios disponiveis para esse barbeiro nessa data.", "erro")
        else:
            conn.execute(
                """INSERT INTO agendamentos
                   (cliente_id, barbeiro_id, servico_id, data, hora,
                    duracao_min, preco, status, criado_em)
                   VALUES (?,?,?,?,?,?,?, 'agendado', ?)""",
                (
                    session["usuario_id"],
                    barbeiro_id,
                    servico_id,
                    data,
                    hora,
                    servico_selecionado["duracao_min"],
                    servico_selecionado["preco"],
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),  # RF17
                ),
            )
            conn.commit()
            conn.close()
            flash("Agendamento confirmado!", "sucesso")
            return redirect(url_for("cliente_agendamentos"))

    if conn.in_transaction:
        conn.rollback()
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
        expediente=expediente,
        turnos_expediente=turnos_expediente,
        dias_atendimento=dias_atendimento,
        hora_selecionada=hora_selecionada,
    )


@app.route("/meus-agendamentos")
@login_obrigatorio("cliente")
def cliente_agendamentos():
    conn = get_db()
    ags = conn.execute(
        """SELECT a.*, s.nome AS servico_nome,
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
# AREA DO BARBEIRO 
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
    query =     """SELECT a.*, s.nome AS servico_nome,
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
# AREA DO ADMINISTRADOR 
# ----------------------------------------------------------------------------
def periodo_relatorio():
    hoje = date.today()
    inicio_padrao = hoje.replace(day=1)
    inicio_texto = request.args.get("inicio") or inicio_padrao.isoformat()
    fim_texto = request.args.get("fim") or hoje.isoformat()
    try:
        inicio = date.fromisoformat(inicio_texto)
        fim = date.fromisoformat(fim_texto)
    except ValueError:
        return None
    if inicio > fim:
        return None
    return inicio, fim


def ocorrencias_dias_semana(inicio, fim):
    total_dias = (fim - inicio).days + 1
    semanas, dias_extras = divmod(total_dias, 7)
    ocorrencias = [semanas] * 7
    for deslocamento in range(dias_extras):
        ocorrencias[(inicio.weekday() + deslocamento) % 7] += 1
    return ocorrencias


def sanitizar_valor_csv(valor):
    texto = "" if valor is None else str(valor)
    if texto.lstrip(" \t\r\n").startswith(("=", "+", "-", "@")):
        return "'" + texto
    return texto


@app.route("/admin")
@app.route("/admin/painel")
@login_obrigatorio("admin")
def admin_dashboard():
    periodo = periodo_relatorio()
    if periodo is None:
        flash("Informe um período de relatório válido.", "erro")
        return redirect(url_for("admin_dashboard"))

    inicio, fim = periodo
    conn = get_db()
    metricas = conn.execute(
        """SELECT COUNT(*) AS total,
                  COALESCE(SUM(CASE WHEN a.status='cancelado' THEN 1 ELSE 0 END), 0)
                      AS cancelamentos,
                  COALESCE(SUM(CASE WHEN a.status='concluido' THEN a.preco ELSE 0 END), 0)
                      AS faturamento,
                  COALESCE(SUM(CASE WHEN a.status!='cancelado'
                                    THEN a.duracao_min ELSE 0 END), 0)
                      AS minutos_reservados
           FROM agendamentos a
           WHERE a.data BETWEEN ? AND ?""",
        (inicio.isoformat(), fim.isoformat()),
    ).fetchone()
    servicos_populares = conn.execute(
        """SELECT s.nome AS servico_nome, COUNT(*) AS quantidade
           FROM agendamentos a
           JOIN servicos s ON s.id = a.servico_id
           WHERE a.data BETWEEN ? AND ?
           GROUP BY s.id, s.nome
           ORDER BY quantidade DESC, s.nome
           LIMIT 5""",
        (inicio.isoformat(), fim.isoformat()),
    ).fetchall()
    expedientes = conn.execute(
        """SELECT d.dia_semana, d.hora_inicio, d.hora_fim
           FROM disponibilidade_barbeiros d
           JOIN barbeiros b ON b.id = d.barbeiro_id
           WHERE b.ativo=1"""
    ).fetchall()
    conn.close()

    ocorrencias = ocorrencias_dias_semana(inicio, fim)
    capacidade_minutos = 0
    for expediente in expedientes:
        duracao_expediente = (
            datetime.strptime(expediente["hora_fim"], "%H:%M")
            - datetime.strptime(expediente["hora_inicio"], "%H:%M")
        )
        capacidade_minutos += max(
            int(duracao_expediente.total_seconds() // 60), 0
        ) * ocorrencias[expediente["dia_semana"]]
    taxa_ocupacao = (
        metricas["minutos_reservados"] / capacidade_minutos * 100
        if capacidade_minutos
        else None
    )
    taxa_cancelamento = (
        metricas["cancelamentos"] / metricas["total"] * 100
        if metricas["total"]
        else 0
    )
    maior_demanda = max(
        (servico["quantidade"] for servico in servicos_populares),
        default=1,
    )

    return render_template(
        "admin_dashboard.html",
        inicio=inicio.isoformat(),
        fim=fim.isoformat(),
        metricas=metricas,
        taxa_ocupacao=taxa_ocupacao,
        taxa_cancelamento=taxa_cancelamento,
        servicos_populares=servicos_populares,
        maior_demanda=maior_demanda,
    )


@app.route("/admin/relatorios/exportar.csv")
@login_obrigatorio("admin")
def admin_relatorio_exportar():
    periodo = periodo_relatorio()
    if periodo is None:
        flash("Informe um período de relatório válido.", "erro")
        return redirect(url_for("admin_dashboard"))
    inicio, fim = periodo

    def gerar_csv():
        conn = get_db()
        buffer = io.StringIO(newline="")
        escritor = csv.writer(buffer, delimiter=";")
        try:
            escritor.writerow(
                [
                    "Data",
                    "Hora",
                    "Cliente",
                    "Barbeiro",
                    "Serviço",
                    "Status",
                    "Duração (min)",
                    "Faturamento de concluídos (R$)",
                ]
            )
            yield "\ufeff" + buffer.getvalue()
            buffer.seek(0)
            buffer.truncate(0)

            agendamentos = conn.execute(
                """SELECT a.data, a.hora, u.nome AS cliente_nome,
                          b.nome AS barbeiro_nome, s.nome AS servico_nome,
                          a.status, a.duracao_min,
                          CASE WHEN a.status='concluido' THEN a.preco ELSE 0 END
                              AS faturamento
                   FROM agendamentos a
                   JOIN usuarios u ON u.id = a.cliente_id
                   JOIN barbeiros b ON b.id = a.barbeiro_id
                   JOIN servicos s ON s.id = a.servico_id
                   WHERE a.data BETWEEN ? AND ?
                   ORDER BY a.data, a.hora, a.id""",
                (inicio.isoformat(), fim.isoformat()),
            )
            for agendamento in agendamentos:
                escritor.writerow(
                    [
                        agendamento["data"],
                        agendamento["hora"],
                        sanitizar_valor_csv(agendamento["cliente_nome"]),
                        sanitizar_valor_csv(agendamento["barbeiro_nome"]),
                        sanitizar_valor_csv(agendamento["servico_nome"]),
                        agendamento["status"],
                        agendamento["duracao_min"],
                        f'{agendamento["faturamento"]:.2f}'.replace(".", ","),
                    ]
                )
                yield buffer.getvalue()
                buffer.seek(0)
                buffer.truncate(0)
        finally:
            conn.close()

    resposta = Response(
        stream_with_context(gerar_csv()),
        content_type="text/csv; charset=utf-8",
    )
    resposta.headers["Content-Disposition"] = (
        f"attachment; filename=relatorio_barbearia_{inicio}_{fim}.csv"
    )
    return resposta


@app.route("/admin/agendamentos")
@login_obrigatorio("admin")
def admin_agendamentos():
    status = request.args.get("status", "")
    conn = get_db()
    query =         """SELECT a.*, s.nome AS servico_nome,
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


# ---- CRUD de servicos  ----
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
    if (
        not nome
        or duracao is None
        or duracao < 5
        or preco is None
        or not math.isfinite(preco)
        or preco < 0
    ):
        flash("Preencha nome, duracao e um preco valido.", "erro")
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


# ---- CRUD de barbeiros  ----
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
    barbeiros = [
        {
            **dict(barbeiro),
            "disponibilidade": obter_disponibilidade_semana(barbeiro["id"]),
        }
        for barbeiro in barbeiros
    ]
    return render_template(
        "admin_barbeiros.html",
        barbeiros=barbeiros,
        dias_semana=DIAS_SEMANA,
    )


@app.route("/admin/barbeiros/salvar", methods=["POST"])
@login_obrigatorio("admin")
def admin_barbeiro_salvar():
    bid = request.form.get("id", type=int)
    nome = request.form.get("nome", "").strip()
    especialidade = request.form.get("especialidade", "").strip()
    email = request.form.get("email", "").strip().lower()
    senha = request.form.get("senha", "")
    ativo = 1 if request.form.get("ativo") == "on" else 0
    dias = sorted({int(dia) for dia in request.form.getlist("dias")})
    hora_inicio = request.form.get("hora_inicio", "09:00")
    hora_fim = request.form.get("hora_fim", "19:00")

    if not nome:
        flash("Informe o nome do barbeiro.", "erro")
        return redirect(url_for("admin_barbeiros"))
    if senha and not senha_forte(senha):
        flash("A senha deve ter entre 12 e 128 caracteres.", "erro")
        return redirect(url_for("admin_barbeiros"))
    if not bid and email and not senha:
        flash("Informe uma senha inicial para criar o acesso do barbeiro.", "erro")
        return redirect(url_for("admin_barbeiros"))
    if not dias or not hora_inicio or not hora_fim or hora_inicio >= hora_fim:
        flash("Informe pelo menos um dia e um horario de atendimento valido.", "erro")
        return redirect(url_for("admin_barbeiros"))

    conn = get_db()
    if bid:  # edicao
        b = conn.execute("SELECT * FROM barbeiros WHERE id=?", (bid,)).fetchone()
        conn.execute(
            "UPDATE barbeiros SET nome=?, especialidade=?, ativo=? WHERE id=?",
            (nome, especialidade, ativo, bid),
        )
        salvar_disponibilidade(conn, bid, dias, hora_inicio, hora_fim)
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
                (nome, email, hash_senha(senha)),
            )
            usuario_id = conn.execute(
                "SELECT id FROM usuarios WHERE email=?", (email,)
            ).fetchone()["id"]
        barbeiro_cursor = conn.execute(
            "INSERT INTO barbeiros (usuario_id, nome, especialidade, ativo) VALUES (?,?,?,?)",
            (usuario_id, nome, especialidade, ativo),
        )
        bid = barbeiro_cursor.lastrowid
        salvar_disponibilidade(conn, bid, dias, hora_inicio, hora_fim)
        flash("Barbeiro cadastrado.", "sucesso")
    conn.commit()
    conn.close()

    notificar_barbeiros()

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
    if b:
        notificar_barbeiros()
    flash("Barbeiro excluido.", "sucesso")
    return redirect(url_for("admin_barbeiros"))


@app.errorhandler(403)
def erro_403(e):
    return render_template("erro.html", codigo=403, mensagem="Acesso nao autorizado."), 403


@app.errorhandler(404)
def erro_404(e):
    return render_template("erro.html", codigo=404, mensagem="Pagina nao encontrada."), 404


if __name__ == "__main__":
    if APP_ENV == "production":
        raise SystemExit(
            "Em produção, execute a aplicação por um servidor WSGI/Socket.IO."
        )
    socketio.run(
        app,
        host=os.environ.get("BARBERAGENDA_HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", "3000")),
        debug=APP_ENV == "development",
    )
