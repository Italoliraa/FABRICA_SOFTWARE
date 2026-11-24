
import hmac
import os
import sqlite3
from datetime import datetime, timedelta
from hashlib import sha256

from opencl_accelerator import filter_available_slots
from werkzeug.security import check_password_hash, generate_password_hash

DB_PATH = os.path.join(os.path.dirname(__file__), "barbearia.db")


HORA_ABERTURA = 9   # 09:00
HORA_FECHAMENTO = 19  # 19:00
INTERVALO_MIN = 30    # grade de horarios de 30 em 30 minutos
PASSWORD_HASH_METHOD = "scrypt:32768:8:1"
MIN_PASSWORD_LENGTH = 12
MAX_PASSWORD_LENGTH = 128
DIAS_SEMANA = (
    (0, "Segunda-feira"),
    (1, "Terca-feira"),
    (2, "Quarta-feira"),
    (3, "Quinta-feira"),
    (4, "Sexta-feira"),
    (5, "Sabado"),
    (6, "Domingo"),
)


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def hash_senha(senha):
    return generate_password_hash(senha, method=PASSWORD_HASH_METHOD)


def senha_forte(senha):
    return (
        isinstance(senha, str)
        and MIN_PASSWORD_LENGTH <= len(senha) <= MAX_PASSWORD_LENGTH
        and not senha.isspace()
    )


def verificar_senha(senha_armazenada, senha):
    if not isinstance(senha, str) or len(senha) > MAX_PASSWORD_LENGTH:
        return False, False
    if (
        len(senha_armazenada) == 64
        and all(caractere in "0123456789abcdef" for caractere in senha_armazenada)
    ):
        senha_legada = sha256(senha.encode("utf-8")).hexdigest()
        valida = hmac.compare_digest(senha_armazenada, senha_legada)
        return valida, valida
    if "$" not in senha_armazenada:
        return False, False
    valida = check_password_hash(senha_armazenada, senha)
    precisa_rehash = valida and not senha_armazenada.startswith(
        PASSWORD_HASH_METHOD + "$"
    )
    return valida, precisa_rehash


def init_db():
    """Cria as tabelas e preenche dados iniciais caso o banco esteja vazio."""
    conn = get_db()
    cur = conn.cursor()

    cur.executescript(
        """
        CREATE TABLE IF NOT EXISTS usuarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            senha TEXT NOT NULL,
            papel TEXT NOT NULL CHECK (papel IN ('admin', 'barbeiro', 'cliente')),
            telefone TEXT
        );

        CREATE TABLE IF NOT EXISTS barbeiros (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            usuario_id INTEGER UNIQUE,
            nome TEXT NOT NULL,
            especialidade TEXT,
            ativo INTEGER NOT NULL DEFAULT 1,
            FOREIGN KEY (usuario_id) REFERENCES usuarios(id) ON DELETE SET NULL
        );

        CREATE TABLE IF NOT EXISTS servicos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL,
            descricao TEXT,
            duracao_min INTEGER NOT NULL,
            preco REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS agendamentos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cliente_id INTEGER NOT NULL,
            barbeiro_id INTEGER NOT NULL,
            servico_id INTEGER NOT NULL,
            data TEXT NOT NULL,
            hora TEXT NOT NULL,
            duracao_min INTEGER NOT NULL,
            preco REAL NOT NULL,
            status TEXT NOT NULL DEFAULT 'agendado'
                CHECK (status IN ('agendado', 'em_atendimento', 'concluido', 'cancelado')),
            criado_em TEXT NOT NULL,
            FOREIGN KEY (cliente_id) REFERENCES usuarios(id) ON DELETE CASCADE,
            FOREIGN KEY (barbeiro_id) REFERENCES barbeiros(id) ON DELETE CASCADE,
            FOREIGN KEY (servico_id) REFERENCES servicos(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS disponibilidade_barbeiros (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            barbeiro_id INTEGER NOT NULL,
            dia_semana INTEGER NOT NULL CHECK (dia_semana BETWEEN 0 AND 6),
            hora_inicio TEXT NOT NULL,
            hora_fim TEXT NOT NULL,
            UNIQUE (barbeiro_id, dia_semana),
            FOREIGN KEY (barbeiro_id) REFERENCES barbeiros(id) ON DELETE CASCADE
        );
        """
    )

    colunas_agendamento = {
        row["name"] for row in cur.execute("PRAGMA table_info(agendamentos)")
    }
    if "duracao_min" not in colunas_agendamento:
        cur.execute(
            "ALTER TABLE agendamentos ADD COLUMN duracao_min INTEGER NOT NULL DEFAULT 30"
        )
        cur.execute(
            """UPDATE agendamentos
               SET duracao_min = COALESCE(
                   (SELECT duracao_min FROM servicos
                    WHERE servicos.id = agendamentos.servico_id),
                   30
               )"""
        )
    if "preco" not in colunas_agendamento:
        cur.execute(
            "ALTER TABLE agendamentos ADD COLUMN preco REAL NOT NULL DEFAULT 0"
        )
        cur.execute(
            """UPDATE agendamentos
               SET preco = COALESCE(
                   (SELECT preco FROM servicos
                    WHERE servicos.id = agendamentos.servico_id),
                   0
               )"""
        )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_agendamentos_data ON agendamentos(data)"
    )

    # Dados iniciais (seed) apenas na primeira execucao
    if cur.execute("SELECT COUNT(*) FROM usuarios").fetchone()[0] == 0:
        senha_admin = os.environ.get("BARBERAGENDA_ADMIN_PASSWORD", "")
        senha_demo = os.environ.get("BARBERAGENDA_DEMO_PASSWORD", "")
        ambiente = os.environ.get("APP_ENV", "development").lower()
        if not senha_forte(senha_admin):
            conn.close()
            raise RuntimeError(
                "Configure BARBERAGENDA_ADMIN_PASSWORD com entre "
                f"{MIN_PASSWORD_LENGTH} e {MAX_PASSWORD_LENGTH} caracteres "
                "antes da primeira inicializacao."
            )
        if ambiente != "production" and senha_demo and not senha_forte(senha_demo):
            conn.close()
            raise RuntimeError(
                "BARBERAGENDA_DEMO_PASSWORD deve ter entre "
                f"{MIN_PASSWORD_LENGTH} e {MAX_PASSWORD_LENGTH} caracteres."
            )
        cur.execute(
            "INSERT INTO usuarios (nome, email, senha, papel, telefone) VALUES (?,?,?,?,?)",
            (
                "Administrador",
                os.environ.get("BARBERAGENDA_ADMIN_EMAIL", "").strip().lower()
                or "admin@barbearia.com",
                hash_senha(senha_admin),
                "admin",
                "",
            ),
        )

        if ambiente != "production" and senha_demo:
            barbeiros_seed = [
                ("Carlos Souza", "carlos@barbearia.com", "Cortes classicos"),
                ("Rafael Lima", "rafael@barbearia.com", "Barba e navalha"),
            ]
            for nome, email, esp in barbeiros_seed:
                cur.execute(
                    "INSERT INTO usuarios (nome, email, senha, papel, telefone) VALUES (?,?,?,?,?)",
                    (nome, email, hash_senha(senha_demo), "barbeiro", ""),
                )
                uid = cur.lastrowid
                cur.execute(
                    "INSERT INTO barbeiros (usuario_id, nome, especialidade, ativo) VALUES (?,?,?,1)",
                    (uid, nome, esp),
                )

            cur.execute(
                "INSERT INTO usuarios (nome, email, senha, papel, telefone) VALUES (?,?,?,?,?)",
                (
                    "Joao Cliente",
                    "joao@email.com",
                    hash_senha(senha_demo),
                    "cliente",
                    "(11) 99999-0000",
                ),
            )

        # Servicos de exemplo (RF02, RF03)
        servicos_seed = [
            ("Corte de cabelo", "Corte masculino tesoura/maquina", 30, 40.0),
            ("Barba", "Aparo e modelagem de barba", 30, 30.0),
            ("Corte + Barba", "Combo completo", 60, 60.0),
            ("Pezinho", "Acabamento", 15, 15.0),
        ]
        cur.executemany(
            "INSERT INTO servicos (nome, descricao, duracao_min, preco) VALUES (?,?,?,?)",
            servicos_seed,
        )

    for barbeiro in cur.execute("SELECT id FROM barbeiros").fetchall():
        if not cur.execute(
            "SELECT 1 FROM disponibilidade_barbeiros WHERE barbeiro_id=? LIMIT 1",
            (barbeiro["id"],),
        ).fetchone():
            cur.executemany(
                """INSERT INTO disponibilidade_barbeiros
                   (barbeiro_id, dia_semana, hora_inicio, hora_fim)
                   VALUES (?,?,?,?)""",
                [(barbeiro["id"], dia, "09:00", "19:00") for dia in range(6)],
            )

    conn.commit()
    conn.close()


def slots_do_dia(hora_inicio=HORA_ABERTURA, hora_fim=HORA_FECHAMENTO):
    """Gera a grade de horarios possiveis do dia (RF06)."""
    slots = []
    if isinstance(hora_inicio, str):
        atual = datetime.strptime(hora_inicio, "%H:%M")
    else:
        atual = datetime(2000, 1, 1, hora_inicio, 0)
    if isinstance(hora_fim, str):
        fim = datetime.strptime(hora_fim, "%H:%M")
    else:
        fim = datetime(2000, 1, 1, hora_fim, 0)
    while atual < fim:
        slots.append(atual.strftime("%H:%M"))
        atual += timedelta(minutes=INTERVALO_MIN)
    return slots


def obter_disponibilidade_semana(barbeiro_id):
    conn = get_db()
    disponibilidade = conn.execute(
        """SELECT dia_semana, hora_inicio, hora_fim
           FROM disponibilidade_barbeiros
           WHERE barbeiro_id=?
           ORDER BY dia_semana""",
        (barbeiro_id,),
    ).fetchall()
    conn.close()
    return disponibilidade


def salvar_disponibilidade(conn, barbeiro_id, dias, hora_inicio, hora_fim):
    conn.execute(
        "DELETE FROM disponibilidade_barbeiros WHERE barbeiro_id=?",
        (barbeiro_id,),
    )
    conn.executemany(
        """INSERT INTO disponibilidade_barbeiros
           (barbeiro_id, dia_semana, hora_inicio, hora_fim)
           VALUES (?,?,?,?)""",
        [(barbeiro_id, dia, hora_inicio, hora_fim) for dia in dias],
    )


def horarios_disponiveis_por_duracao(barbeiro_id, data, duracoes_min, conn=None):
    """Calcula horarios livres para cada duracao de servico informada."""
    duracoes = tuple(sorted({duracao for duracao in duracoes_min if duracao > 0}))
    disponibilidade = {duracao: [] for duracao in duracoes}
    if not duracoes:
        return disponibilidade

    try:
        data_consulta = datetime.strptime(data, "%Y-%m-%d").date()
    except ValueError:
        return disponibilidade

    owns_connection = conn is None
    connection = conn or get_db()
    try:
        expediente = connection.execute(
            """SELECT hora_inicio, hora_fim
               FROM disponibilidade_barbeiros
               WHERE barbeiro_id=? AND dia_semana=?""",
            (barbeiro_id, data_consulta.weekday()),
        ).fetchone()
        if not expediente:
            return disponibilidade

        agendamentos = connection.execute(
            """SELECT a.hora, COALESCE(a.duracao_min, s.duracao_min) AS duracao_min
               FROM agendamentos a
               JOIN servicos s ON s.id = a.servico_id
               WHERE a.barbeiro_id=? AND a.data=? AND a.status != 'cancelado'""",
            (barbeiro_id, data),
        ).fetchall()
        intervalos_ocupados = []
        for agendamento in agendamentos:
            inicio_ocupado = datetime.combine(
                data_consulta,
                datetime.strptime(agendamento["hora"], "%H:%M").time(),
            )
            fim_ocupado = inicio_ocupado + timedelta(
                minutes=agendamento["duracao_min"]
            )
            intervalos_ocupados.append((inicio_ocupado, fim_ocupado))

        inicio_expediente = datetime.combine(
            data_consulta,
            datetime.strptime(expediente["hora_inicio"], "%H:%M").time(),
        )
        fim_expediente = datetime.combine(
            data_consulta,
            datetime.strptime(expediente["hora_fim"], "%H:%M").time(),
        )
        horarios_candidatos = [
            (
                horario,
                datetime.combine(
                    data_consulta,
                    datetime.strptime(horario, "%H:%M").time(),
                ),
            )
            for horario in slots_do_dia(
                expediente["hora_inicio"],
                expediente["hora_fim"],
            )
        ]
        if horarios_candidatos:
            inicios_ocupados = {agendamento["hora"] for agendamento in agendamentos}
            horarios_filtrados = set(
                filter_available_slots(
                    [horario for horario, _ in horarios_candidatos],
                    inicios_ocupados,
                )
            )
            horarios_candidatos = [
                (horario, inicio)
                for horario, inicio in horarios_candidatos
                if horario in horarios_filtrados
            ]

        agora = datetime.now()
        for duracao in duracoes:
            tempo_servico = timedelta(minutes=duracao)
            for horario, inicio in horarios_candidatos:
                fim = inicio + tempo_servico
                if data_consulta == agora.date() and inicio <= agora:
                    continue
                if inicio < inicio_expediente or fim > fim_expediente:
                    continue
                if any(
                    inicio < fim_ocupado and inicio_ocupado < fim
                    for inicio_ocupado, fim_ocupado in intervalos_ocupados
                ):
                    continue
                disponibilidade[duracao].append(horario)
    finally:
        if owns_connection:
            connection.close()

    return disponibilidade


def horarios_disponiveis(barbeiro_id, data, duracao_min=None, conn=None):
    """Retorna horarios sem conflito e com tempo para concluir o servico."""
    owns_connection = conn is None
    connection = conn or get_db()
    try:
        if duracao_min is None:
            duracao_min = connection.execute(
                "SELECT COALESCE(MAX(duracao_min), ?) FROM servicos",
                (INTERVALO_MIN,),
            ).fetchone()[0]
        return horarios_disponiveis_por_duracao(
            barbeiro_id,
            data,
            [duracao_min],
            conn=connection,
        ).get(duracao_min, [])
    finally:
        if owns_connection:
            connection.close()
