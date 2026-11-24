import csv
import io
import os
import re
import runpy
import secrets
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from threading import Barrier
from unittest import mock

import db


class BookingAvailabilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.original_db_path = db.DB_PATH
        cls.env_patch = mock.patch.dict(
            os.environ,
            {
                "APP_ENV": "development",
                "BARBERAGENDA_SECRET_KEY": secrets.token_urlsafe(32),
                "BARBERAGENDA_ADMIN_PASSWORD": "AdminPassword!2026",
                "BARBERAGENDA_DEMO_PASSWORD": "ClientPassword!2026",
            },
        )
        cls.env_patch.start()
        db.DB_PATH = str(Path(cls.temp_dir.name) / "test.db")
        db.init_db()

        from app import app, socketio

        cls.app = app
        cls.socketio = socketio
        cls.app.config["TESTING"] = True
        conn = db.get_db()
        cls.initial_services = {
            row["id"]: (row["duracao_min"], row["preco"])
            for row in conn.execute(
                "SELECT id, duracao_min, preco FROM servicos"
            ).fetchall()
        }
        conn.close()

    @classmethod
    def tearDownClass(cls):
        db.DB_PATH = cls.original_db_path
        cls.temp_dir.cleanup()
        cls.env_patch.stop()

    def setUp(self):
        conn = db.get_db()
        conn.execute("DELETE FROM agendamentos")
        for service_id, (duration, price) in self.initial_services.items():
            conn.execute(
                "UPDATE servicos SET duracao_min=?, preco=? WHERE id=?",
                (duration, price, service_id),
            )
        conn.commit()
        self.barbeiro_id = conn.execute(
            "SELECT id FROM barbeiros ORDER BY id LIMIT 1"
        ).fetchone()["id"]
        self.cliente_id = conn.execute(
            "SELECT id FROM usuarios WHERE email='joao@email.com'"
        ).fetchone()["id"]
        self.servicos = {
            row["duracao_min"]: row["id"]
            for row in conn.execute(
                "SELECT id, duracao_min FROM servicos ORDER BY id"
            ).fetchall()
        }
        self.servicos_por_nome = {
            row["nome"]: dict(row)
            for row in conn.execute("SELECT * FROM servicos").fetchall()
        }
        conn.close()
        self.data = self._proximo_dia_de_atendimento()

    @staticmethod
    def _proximo_dia_de_atendimento():
        for offset in range(1, 8):
            candidate = date.today() + timedelta(days=offset)
            if candidate.weekday() < 6:
                return candidate.strftime("%Y-%m-%d")
        raise AssertionError("Nao foi encontrado um dia de atendimento")

    def _inserir_agendamento(
        self,
        hora,
        duracao,
        status="agendado",
        servico_nome=None,
        preco=None,
    ):
        servico = (
            self.servicos_por_nome[servico_nome]
            if servico_nome
            else next(
                item
                for item in self.servicos_por_nome.values()
                if item["id"] == self.servicos[duracao]
            )
        )
        conn = db.get_db()
        conn.execute(
            """INSERT INTO agendamentos
               (cliente_id, barbeiro_id, servico_id, data, hora,
                duracao_min, preco, status, criado_em)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                self.cliente_id,
                self.barbeiro_id,
                servico["id"],
                self.data,
                hora,
                duracao,
                servico["preco"] if preco is None else preco,
                status,
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            ),
        )
        conn.commit()
        conn.close()

    def _post_booking(self, client, hora, duracao, csrf_token):
        return client.post(
            "/agendar",
            data={
                "csrf_token": csrf_token,
                "acao": "confirmar",
                "servico_id": self.servicos[duracao],
                "barbeiro_id": self.barbeiro_id,
                "data": self.data,
                "hora": hora,
            },
        )

    @staticmethod
    def _csrf_token(client):
        response = client.get("/login")
        match = re.search(
            r'name="csrf_token" value="([^"]+)"',
            response.get_data(as_text=True),
        )
        if match is None:
            raise AssertionError("O formulário de login não incluiu um token CSRF")
        return match.group(1)

    def _login(self, client, email, password):
        token = self._csrf_token(client)
        response = client.post(
            "/login",
            data={"email": email, "senha": password, "csrf_token": token},
        )
        self.assertEqual(response.status_code, 302)
        return self._csrf_token(client)

    def test_password_hash_uses_scrypt(self):
        stored = db.hash_senha("StrongPassword!2026")
        self.assertTrue(stored.startswith("scrypt:32768:8:1$"))
        self.assertEqual(
            db.verificar_senha(stored, "StrongPassword!2026"),
            (True, False),
        )
        self.assertEqual(
            db.verificar_senha(stored, "IncorrectPassword!"),
            (False, False),
        )

    def test_new_database_requires_an_admin_password(self):
        unconfigured_path = Path(self.temp_dir.name) / "unconfigured.db"
        original_db_path = db.DB_PATH
        try:
            db.DB_PATH = str(unconfigured_path)
            with mock.patch.dict(os.environ, {"BARBERAGENDA_ADMIN_PASSWORD": ""}):
                with self.assertRaisesRegex(
                    RuntimeError, "BARBERAGENDA_ADMIN_PASSWORD"
                ):
                    db.init_db()
        finally:
            db.DB_PATH = original_db_path

    def test_production_requires_a_secret_and_secures_session_cookies(self):
        app_path = Path(__file__).resolve().parents[1] / "app.py"
        with mock.patch.dict(
            os.environ,
            {"APP_ENV": "production", "BARBERAGENDA_SECRET_KEY": ""},
        ):
            with self.assertRaisesRegex(
                RuntimeError, "BARBERAGENDA_SECRET_KEY"
            ):
                runpy.run_path(str(app_path))

        with mock.patch.dict(
            os.environ,
            {
                "APP_ENV": "production",
                "BARBERAGENDA_SECRET_KEY": secrets.token_urlsafe(32),
            },
        ):
            production_app = runpy.run_path(str(app_path))["app"]

        self.assertTrue(production_app.config["SESSION_COOKIE_SECURE"])
        self.assertTrue(production_app.config["SESSION_COOKIE_HTTPONLY"])
        self.assertEqual(production_app.config["SESSION_COOKIE_SAMESITE"], "Lax")

    def test_successful_legacy_login_upgrades_password_hash(self):
        legacy_password = "LegacyPassword!2026"
        conn = db.get_db()
        conn.execute(
            "UPDATE usuarios SET senha=? WHERE id=?",
            (
                sha256(legacy_password.encode("utf-8")).hexdigest(),
                self.cliente_id,
            ),
        )
        conn.commit()
        conn.close()

        with self.app.test_client() as client:
            self._login(client, "joao@email.com", legacy_password)

        conn = db.get_db()
        stored = conn.execute(
            "SELECT senha FROM usuarios WHERE id=?",
            (self.cliente_id,),
        ).fetchone()["senha"]
        conn.close()
        self.assertTrue(stored.startswith("scrypt:32768:8:1$"))

    def test_post_without_csrf_token_is_rejected(self):
        with self.app.test_client() as client:
            response = client.post(
                "/login",
                data={
                    "email": "admin@barbearia.com",
                    "senha": "AdminPassword!2026",
                },
            )
        self.assertEqual(response.status_code, 400)

    def test_logout_requires_csrf_protected_post(self):
        with self.app.test_client() as client:
            csrf_token = self._login(
                client, "admin@barbearia.com", "AdminPassword!2026"
            )
            self.assertEqual(client.get("/logout").status_code, 405)
            response = client.post(
                "/logout",
                data={"csrf_token": csrf_token},
            )
            self.assertEqual(response.status_code, 302)
            self.assertEqual(client.get("/admin").status_code, 302)

    def test_new_barber_login_requires_an_explicit_strong_password(self):
        with self.app.test_client() as client:
            csrf_token = self._login(
                client, "admin@barbearia.com", "AdminPassword!2026"
            )
            for password in ("", "short"):
                response = client.post(
                    "/admin/barbeiros/salvar",
                    data={
                        "csrf_token": csrf_token,
                        "nome": "Novo barbeiro",
                        "email": "novo@barbearia.com",
                        "senha": password,
                        "dias": ["0"],
                        "hora_inicio": "09:00",
                        "hora_fim": "19:00",
                    },
                )
                self.assertEqual(response.status_code, 302)

        conn = db.get_db()
        user = conn.execute(
            "SELECT id FROM usuarios WHERE email='novo@barbearia.com'"
        ).fetchone()
        conn.close()
        self.assertIsNone(user)

    def test_socketio_connection_still_works_with_csrf_enabled(self):
        client = self.socketio.test_client(self.app)
        self.assertTrue(client.is_connected())
        client.disconnect()

    def test_existing_service_blocks_overlapping_intervals(self):
        self._inserir_agendamento("10:00", 60)
        with mock.patch.object(
            db,
            "filter_available_slots",
            side_effect=lambda slots, occupied: [
                slot for slot in slots if slot not in occupied
            ],
        ):
            slots = db.horarios_disponiveis(
                self.barbeiro_id, self.data, 30
            )

        self.assertNotIn("10:00", slots)
        self.assertNotIn("10:30", slots)
        self.assertIn("11:00", slots)

    def test_cancelled_booking_does_not_block_availability(self):
        self._inserir_agendamento("10:00", 60, status="cancelado")
        with mock.patch.object(
            db,
            "filter_available_slots",
            side_effect=lambda slots, occupied: [
                slot for slot in slots if slot not in occupied
            ],
        ):
            slots = db.horarios_disponiveis(
                self.barbeiro_id, self.data, 30
            )

        self.assertIn("10:00", slots)
        self.assertIn("10:30", slots)

    def test_service_must_fit_inside_working_hours(self):
        with mock.patch.object(
            db,
            "filter_available_slots",
            side_effect=lambda slots, occupied: [
                slot for slot in slots if slot not in occupied
            ],
        ):
            slots_30 = db.horarios_disponiveis(
                self.barbeiro_id, self.data, 30
            )
            slots_60 = db.horarios_disponiveis(
                self.barbeiro_id, self.data, 60
            )

        self.assertIn("18:30", slots_30)
        self.assertIn("18:00", slots_60)
        self.assertNotIn("18:30", slots_60)

    def test_existing_booking_keeps_its_original_duration(self):
        self._inserir_agendamento("10:00", 60)
        conn = db.get_db()
        conn.execute(
            "UPDATE servicos SET duracao_min=30 WHERE id=?",
            (self.servicos[60],),
        )
        conn.commit()
        conn.close()

        with mock.patch.object(
            db,
            "filter_available_slots",
            side_effect=lambda slots, occupied: [
                slot for slot in slots if slot not in occupied
            ],
        ):
            slots = db.horarios_disponiveis(
                self.barbeiro_id, self.data, 30
            )

        self.assertNotIn("10:30", slots)
        self.assertIn("11:00", slots)

    def test_init_db_migrates_existing_bookings(self):
        legacy_path = Path(self.temp_dir.name) / "legacy.db"
        original_db_path = db.DB_PATH
        try:
            db.DB_PATH = str(legacy_path)
            conn = sqlite3.connect(legacy_path)
            conn.execute(
                """CREATE TABLE usuarios (
                       id INTEGER PRIMARY KEY,
                       nome TEXT NOT NULL,
                       email TEXT NOT NULL UNIQUE,
                       senha TEXT NOT NULL,
                       papel TEXT NOT NULL,
                       telefone TEXT
                   )"""
            )
            conn.execute(
                """CREATE TABLE barbeiros (
                       id INTEGER PRIMARY KEY,
                       usuario_id INTEGER,
                       nome TEXT NOT NULL,
                       especialidade TEXT,
                       ativo INTEGER NOT NULL DEFAULT 1
                   )"""
            )
            conn.execute(
                """CREATE TABLE servicos (
                       id INTEGER PRIMARY KEY,
                       nome TEXT NOT NULL,
                       descricao TEXT,
                       duracao_min INTEGER NOT NULL,
                       preco REAL NOT NULL
                   )"""
            )
            conn.execute(
                """CREATE TABLE agendamentos (
                       id INTEGER PRIMARY KEY AUTOINCREMENT,
                       cliente_id INTEGER NOT NULL,
                       barbeiro_id INTEGER NOT NULL,
                       servico_id INTEGER NOT NULL,
                       data TEXT NOT NULL,
                       hora TEXT NOT NULL,
                       status TEXT NOT NULL DEFAULT 'agendado',
                       criado_em TEXT NOT NULL
                   )"""
            )
            conn.execute(
                """INSERT INTO usuarios
                   (id, nome, email, senha, papel, telefone)
                   VALUES (1, 'Cliente', 'cliente@test.com', 'senha', 'cliente', '')"""
            )
            conn.execute(
                """INSERT INTO barbeiros
                   (id, nome, especialidade, ativo)
                   VALUES (1, 'Barbeiro', '', 1)"""
            )
            conn.execute(
                """INSERT INTO servicos
                   (id, nome, descricao, duracao_min, preco)
                   VALUES (1, 'Combo', '', 60, 60)"""
            )
            conn.execute(
                """INSERT INTO agendamentos
                   (cliente_id, barbeiro_id, servico_id, data, hora, criado_em)
                   VALUES (1, 1, 1, '2030-01-07', '10:00', '2030-01-01 00:00:00')"""
            )
            conn.commit()
            conn.close()
            db.init_db()

            conn = db.get_db()
            snapshot = conn.execute(
            "SELECT duracao_min, preco FROM agendamentos"
            ).fetchone()
            duracao = snapshot["duracao_min"]
            preco = snapshot["preco"]
            conn.close()
        finally:
            db.DB_PATH = original_db_path

        self.assertEqual(duracao, 60)
        self.assertEqual(preco, 60)

    def test_booking_rejects_an_overlapping_service(self):
        with self.app.test_client() as client:
            csrf_token = self._login(
                client, "joao@email.com", "ClientPassword!2026"
            )
            with mock.patch.object(
                db,
                "filter_available_slots",
                side_effect=lambda slots, occupied: [
                    slot for slot in slots if slot not in occupied
                ],
            ):
                first = self._post_booking(client, "10:00", 60, csrf_token)
                second = self._post_booking(client, "10:30", 30, csrf_token)

        self.assertEqual(first.status_code, 302)
        self.assertEqual(second.status_code, 200)
        conn = db.get_db()
        count = conn.execute(
            "SELECT COUNT(*) FROM agendamentos"
        ).fetchone()[0]
        conn.close()
        self.assertEqual(count, 1)

    def test_barbeiros_page_only_offers_services_that_fit_the_slot(self):
        self._inserir_agendamento("10:00", 60)
        with self.app.test_client() as client:
            self._login(
                client, "joao@email.com", "ClientPassword!2026"
            )
            with mock.patch.object(
                db,
                "filter_available_slots",
                side_effect=lambda slots, occupied: [
                    slot for slot in slots if slot not in occupied
                ],
            ):
                response = client.get(
                    "/barbeiros",
                    query_string={
                        "barbeiro_id": self.barbeiro_id,
                        "data": self.data,
                    },
                )

        self.assertEqual(response.status_code, 200)
        slot = re.search(
            r'<button class="slot-link"[^>]*data-hora="09:30"[^>]*>',
            response.get_data(as_text=True),
            flags=re.DOTALL,
        )
        self.assertIsNotNone(slot)
        servicos_disponiveis = re.search(
            r'data-servicos="([^"]*)"', slot.group()
        ).group(1).split(",")
        self.assertIn(str(self.servicos[30]), servicos_disponiveis)
        self.assertNotIn(str(self.servicos[60]), servicos_disponiveis)

    def test_concurrent_confirmations_cannot_take_the_same_slot(self):
        barrier = Barrier(2)

        def book():
            with self.app.test_client() as client:
                csrf_token = self._login(
                    client, "joao@email.com", "ClientPassword!2026"
                )
                barrier.wait(timeout=5)
                return self._post_booking(
                    client, "12:00", 30, csrf_token
                ).status_code

        with mock.patch.object(
            db,
            "filter_available_slots",
            side_effect=lambda slots, occupied: [
                slot for slot in slots if slot not in occupied
            ],
        ):
            with ThreadPoolExecutor(max_workers=2) as executor:
                statuses = list(executor.map(lambda _: book(), range(2)))

        self.assertCountEqual(statuses, [200, 302])
        conn = db.get_db()
        count = conn.execute(
            "SELECT COUNT(*) FROM agendamentos"
        ).fetchone()[0]
        conn.close()
        self.assertEqual(count, 1)

    def test_admin_dashboard_reports_revenue_demand_and_cancellations(self):
        self._inserir_agendamento(
            "09:00", 30, status="concluido", servico_nome="Corte de cabelo"
        )
        self._inserir_agendamento(
            "09:30", 30, status="cancelado", servico_nome="Corte de cabelo"
        )
        self._inserir_agendamento(
            "10:00", 30, status="agendado", servico_nome="Barba"
        )
        self._inserir_agendamento(
            "11:00", 60, status="concluido", servico_nome="Corte + Barba"
        )
        conn = db.get_db()
        conn.execute(
            "UPDATE servicos SET preco=999 WHERE nome='Corte de cabelo'"
        )
        conn.commit()
        conn.close()
        with self.app.test_client() as client:
            self._login(
                client, "admin@barbearia.com", "AdminPassword!2026"
            )
            response = client.get(
                "/admin/painel",
                query_string={"inicio": self.data, "fim": self.data},
            )

        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("R$ 100,00", html)
        self.assertIn("10.0%", html)
        self.assertIn("25.0%", html)
        self.assertIn("Corte de cabelo", html)
        self.assertIn("<strong>2</strong>", html)

    def test_admin_csv_exports_period_rows_and_neutralizes_formulas(self):
        self._inserir_agendamento(
            "09:00", 30, status="concluido", servico_nome="Corte de cabelo"
        )
        self._inserir_agendamento(
            "09:30", 30, status="cancelado", servico_nome="Barba"
        )
        conn = db.get_db()
        conn.execute(
            "UPDATE usuarios SET nome='=2+2' WHERE id=?",
            (self.cliente_id,),
        )
        conn.execute(
            "UPDATE servicos SET preco=999 WHERE nome='Corte de cabelo'"
        )
        conn.commit()
        conn.close()

        with self.app.test_client() as client:
            self._login(
                client, "admin@barbearia.com", "AdminPassword!2026"
            )
            response = client.get(
                "/admin/relatorios/exportar.csv",
                query_string={"inicio": self.data, "fim": self.data},
            )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.mimetype == "text/csv")
        rows = list(
            csv.reader(
                io.StringIO(response.get_data(as_text=True).lstrip("\ufeff")),
                delimiter=";",
            )
        )
        self.assertEqual(rows[0][-1], "Faturamento de concluídos (R$)")
        self.assertTrue(any(row[2] == "'=2+2" for row in rows[1:]))
        self.assertIn("40,00", [row[-1] for row in rows[1:]])
        self.assertIn("0,00", [row[-1] for row in rows[1:]])


if __name__ == "__main__":
    unittest.main()
