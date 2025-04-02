from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import pandas as pd
from datetime import datetime
from sklearn.ensemble import IsolationForest
from sqlalchemy import text
import sqlalchemy
import os
from dotenv import load_dotenv
from typing import Optional

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")
engine = sqlalchemy.create_engine(DATABASE_URL)

app = FastAPI()

class Transacao(BaseModel):
    id: Optional[int] = None
    cliente: str
    valor_transacao: float
    data: str
    status: str
    justificativa: Optional[str] = None

class FeedbackAuditoria(BaseModel):
    id_transacao: int
    rotulo: str  # 'violacao_confirmada', 'falso_positivo', 'nao_avaliado'
    observacao: str = ""

@app.get("/")
def root():
    return {"message": "AuditAI API online"}

@app.get("/relatorio")
def relatorio():
    try:
        query = "SELECT * FROM transacoes ORDER BY data DESC"
        df = pd.read_sql(query, engine)
        df['data'] = pd.to_datetime(df['data'])
        return df.to_dict(orient='records')
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/auditoria")
def auditar_transacoes():
    try:
        import json
        with open("regras_compliance_auditai.json", "r", encoding="utf-8") as f:
            regras = json.load(f)

        df = pd.read_sql("""
            SELECT id, cliente, valor_transacao, data, status, justificativa
            FROM transacoes
            WHERE data >= NOW() - INTERVAL '30 days'
        """, engine)
        df['data'] = pd.to_datetime(df['data'])

        def analisar_justificativa_regex(justificativa: str):
            resultados = []
            padroes = {
                "CPF": r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b",
                "E-mail": r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[a-z]{2,}\b",
                "PIX": r"\bpix\b",
                "RG": r"\b\d{7,10}\b",
                "Telefone": r"\(?\d{2}\)?\s?\d{4,5}-\d{4}",
                "Nome completo": r"\bnome\s+completo\b",
                "Endereço": r"\bendere[cç]o\b",
                "CNPJ": r"\b\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}\b"
            }
            for nome, padrao in padroes.items():
                try:
                    if re.search(padrao, justificativa, re.IGNORECASE):
                        resultados.append(f"Dado sensível detectado: {nome}")
                except Exception:
                    continue
            return resultados

        def verificar_regras_temporais(data_transacao):
            violacoes = []
            if data_transacao.hour < 8 or data_transacao.hour >= 18:
                violacoes.append({
                    "codigo": "RT001",
                    "descricao": "Transação fora do horário comercial",
                    "origem": "Compliance Interno",
                    "acao_recomendada": "Verificar motivo da transação fora do expediente",
                    "base_legal": "Política interna de integridade e acesso"
                })
            if data_transacao.weekday() >= 5:
                violacoes.append({
                    "codigo": "RT002",
                    "descricao": "Transação realizada em final de semana",
                    "origem": "Compliance Interno",
                    "acao_recomendada": "Confirmar autorização e motivo da operação",
                    "base_legal": "Política de conformidade operacional"
                })
            return violacoes

        def aplicar_regras_compliance(row):
            violacoes = []
            for regra in regras:
                campo = regra.get("campo_relevante", "").lower()
                condicao = regra.get("condicao", "").lower()

                if "valor_transacao" in condicao and ">" in condicao:
                    try:
                        limite = float(condicao.split(">")[1].split()[0])
                        if row.get("valor_transacao", 0) > limite and not row.get("justificativa"):
                            violacoes.append(regra)
                    except:
                        continue

                if "justificativa" in condicao and "dado pessoal" in condicao:
                    just = row.get("justificativa", "")
                    violacoes_regex = analisar_justificativa_regex(just)
                    if violacoes_regex:
                        regra["descricao"] += f" ({', '.join(violacoes_regex)})"
                        violacoes.append(regra)

                elif campo == "justificativa" and condicao == "contém dado pessoal":
                    just = row.get("justificativa", "").lower()
                    if any(term in just for term in ["cpf", "nome", "rg", "email"]):
                        violacoes.append(regra)

                if "final de semana" in condicao or "horário comercial" in condicao:
                    data_transacao = pd.to_datetime(row.get("data"))
                    violacoes.extend(verificar_regras_temporais(data_transacao))

            return violacoes

        df["violacoes_compliance"] = df.apply(lambda row: aplicar_regras_compliance(row), axis=1)
        resultado = df[["id", "cliente", "valor_transacao", "data", "status", "justificativa", "violacoes_compliance"]]
        return {"auditorias": resultado.to_dict(orient="records")}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/transacao")
def inserir_transacao(transacao: Transacao):
    try:
        query = text("""
            INSERT INTO transacoes (cliente, valor_transacao, data, status, justificativa)
            VALUES (:cliente, :valor_transacao, :data, :status, :justificativa)
        """)
        with engine.connect() as connection:
            connection.execute(query, {
                "cliente": transacao.cliente,
                "valor_transacao": transacao.valor_transacao,
                "data": transacao.data,
                "status": transacao.status,
                "justificativa": transacao.justificativa
            })
        return {"mensagem": "Transação inserida com sucesso."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

