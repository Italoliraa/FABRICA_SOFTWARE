"""
Camada de acesso ao banco de dados (RF18).
Usa apenas a biblioteca padrao do Python (sqlite3), sem ORM e sem JavaScript.
"""
import sqlite3
from datetime import datetime, timedelta
from hashlib import sha256
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "barbearia.db")

# Horario de funcionamento da barbearia
HORA_ABERTURA = 9   # 09:00
HORA_FECHAMENTO = 19  # 19:00
INTERVALO_MIN = 30    # grade de horarios de 30 em 30 minutos


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def hash_senha(senha):
    return sha256(senha.encode("utf-8")).hexdigest()


def init_db():
    """Cria as tabelas e popula dados iniciais caso o banco esteja vazio."""
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
            status TEXT NOT NULL DEFAULT 'agendado'
                CHECK (status IN ('agendado', 'em_atendimento', 'concluido', 'cancelado')),
            criado_em TEXT NOT NULL,
            FOREIGN KEY (cliente_id) REFERENCES usuarios(id) ON DELETE CASCADE,
            FOREIGN KEY (barbeiro_id) REFERENCES barbeiros(id) ON DELETE CASCADE,
            FOREIGN KEY (servico_id) REFERENCES servicos(id) ON DELETE CASCADE
        );
        """
    )

    # Dados iniciais (seed) apenas na primeira execucao
    if cur.execute("SELECT COUNT(*) FROM usuarios").fetchone()[0] == 0:
        cur.execute(
            "INSERT INTO usuarios (nome, email, senha, papel, telefone) VALUES (?,?,?,?,?)",
            ("Administrador", "admin@barbearia.com", hash_senha("admin123"), "admin", ""),
        )

        # Barbeiros de exemplo (cada um com seu login)
        barbeiros_seed = [
            ("Carlos Souza", "carlos@barbearia.com", "Cortes classicos"),
            ("Rafael Lima", "rafael@barbearia.com", "Barba e navalha"),
        ]
        for nome, email, esp in barbeiros_seed:
            cur.execute(
                "INSERT INTO usuarios (nome, email, senha, papel, telefone) VALUES (?,?,?,?,?)",
                (nome, email, hash_senha("barbeiro123"), "barbeiro", ""),
            )
            uid = cur.lastrowid
            cur.execute(
                "INSERT INTO barbeiros (usuario_id, nome, especialidade, ativo) VALUES (?,?,?,1)",
                (uid, nome, esp),
            )

        # Cliente de exemplo
        cur.execute(
            "INSERT INTO usuarios (nome, email, senha, papel, telefone) VALUES (?,?,?,?,?)",
            ("Joao Cliente", "joao@email.com", hash_senha("cliente123"), "cliente", "(11) 99999-0000"),
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

    conn.commit()
    conn.close()


def slots_do_dia():
    """Gera a grade de horarios possiveis do dia (RF06)."""
    slots = []
    atual = datetime(2000, 1, 1, HORA_ABERTURA, 0)
    fim = datetime(2000, 1, 1, HORA_FECHAMENTO, 0)
    while atual < fim:
        slots.append(atual.strftime("%H:%M"))
        atual += timedelta(minutes=INTERVALO_MIN)
    return slots


def horarios_disponiveis(barbeiro_id, data):
    """Retorna os horarios livres de um barbeiro numa data (RF06, RF08)."""
    conn = get_db()
    ocupados = {
        row["hora"]
        for row in conn.execute(
            "SELECT hora FROM agendamentos WHERE barbeiro_id=? AND data=? AND status != 'cancelado'",
            (barbeiro_id, data),
        ).fetchall()
    }
    conn.close()

    disponiveis = [s for s in slots_do_dia() if s not in ocupados]

    # Se a data for hoje, remove horarios que ja passaram
    hoje = datetime.now().strftime("%Y-%m-%d")
    if data == hoje:
        agora = datetime.now().strftime("%H:%M")
        disponiveis = [s for s in disponiveis if s > agora]

    return disponiveis
