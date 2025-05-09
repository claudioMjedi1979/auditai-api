from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import pandas as pd
from datetime import datetime
from sqlalchemy import text
import sqlalchemy
import os
import re
import json
from dotenv import load_dotenv
from typing import Optional
import joblib
from sklearn.ensemble import RandomForestClassifier

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
    rotulo: str
    observacao: Optional[str] = ""

class TransacaoIA(BaseModel):
    valor_transacao: float
    data: str
    justificativa: Optional[str] = None

class Risco(BaseModel):
    titulo: str
    descricao: str
    categoria: str
    probabilidade: str
    impacto: str
    status: str

class Controle(BaseModel):
    id_risco: int
    nome: str
    tipo: str
    descricao: str
    eficacia: str
    responsavel: str

@app.get("/")
def root():
    return {"message": "AuditAI API online"}

@app.get("/relatorio")
def relatorio():
    try:
        query = "SELECT * FROM transacoes ORDER BY data DESC"
        df = pd.read_sql(query, engine)
        df["data"] = pd.to_datetime(df["data"])
        return df.to_dict(orient="records")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/auditoria")
def auditar_transacoes():
    try:
        regras = []
        for arquivo in ["regras_compliance_auditai.json", "regras_compliance_auditai_extensivas.json"]:
            if os.path.exists(arquivo):
                with open(arquivo, "r", encoding="utf-8") as f:
                    regras.extend(json.load(f))

        df = pd.read_sql("""
            SELECT id, cliente, valor_transacao, data, status, justificativa
            FROM transacoes
            WHERE data >= NOW() - INTERVAL '30 days'
        """, engine)
        df["data"] = pd.to_datetime(df["data"])

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
                if justificativa and re.search(padrao, justificativa, re.IGNORECASE):
                    resultados.append(f"Dado sensível detectado: {nome}")
            return resultados

        def regras_temporais(data):
            violacoes = []
            data_obj = pd.to_datetime(data)
            if data_obj.hour < 8 or data_obj.hour >= 18:
                violacoes.append({
                    "codigo": "HOR001",
                    "descricao": "Transação fora do horário comercial",
                    "origem": "Política interna",
                    "acao_recomendada": "Revisar transações fora do expediente",
                    "base_legal": "Controles internos"
                })
            if data_obj.weekday() >= 5:
                violacoes.append({
                    "codigo": "HOR002",
                    "descricao": "Transação realizada no final de semana",
                    "origem": "Política interna",
                    "acao_recomendada": "Confirmar autorização da operação",
                    "base_legal": "Controles internos"
                })
            return violacoes

        def aplicar_regras(row):
            violacoes = []
            for regra in regras:
                campo = regra.get("campo_relevante", "").lower()
                condicao = regra.get("condicao", "").lower()
                if campo == "valor_transacao" and ">" in condicao:
                    try:
                        limite = float(condicao.split(">")[1].split()[0])
                        if row["valor_transacao"] > limite and not row["justificativa"]:
                            violacoes.append(regra)
                    except:
                        continue
                elif campo == "justificativa" and "dado pessoal" in condicao:
                    just = row.get("justificativa", "")
                    resultados = analisar_justificativa_regex(just)
                    if resultados:
                        nova_regra = regra.copy()
                        nova_regra["descricao"] += f" ({', '.join(resultados)})"
                        violacoes.append(nova_regra)
                elif campo == "cliente" and "estrangeiro" in condicao:
                    if "ltd" in row.get("cliente", "").lower() or "inc" in row.get("cliente", "").lower():
                        violacoes.append(regra)
                elif campo == "status/data" and "pendente" in condicao:
                    if row.get("status") == "Pendente":
                        data = pd.to_datetime(row.get("data"))
                        if (datetime.now() - data).days > 7:
                            violacoes.append(regra)
                elif condicao.startswith("condicao_"):
                    observacao = regra.copy()
                    observacao["descricao"] += " ⚠️ Regra genérica não aplicada automaticamente"
                    violacoes.append(observacao)
            violacoes.extend(regras_temporais(row.get("data")))
            return violacoes

        df["violacoes_compliance"] = df.apply(aplicar_regras, axis=1)
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
            connection.execute(query, transacao.dict())
        return {"mensagem": "Transação inserida com sucesso."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/rotular_transacao")
def rotular_transacao(feedback: FeedbackAuditoria):
    try:
        insert_query = text("""
            INSERT INTO feedback_auditoria (id_transacao, rotulo, observacao, data_registro)
            VALUES (:id_transacao, :rotulo, :observacao, NOW())
        """)
        with engine.connect() as connection:
            connection.execute(insert_query, {
                "id_transacao": feedback.id_transacao,
                "rotulo": feedback.rotulo,
                "observacao": feedback.observacao or ""
            })

        df_transacoes = pd.read_sql("SELECT * FROM transacoes", engine)
        df_feedbacks = pd.read_sql("SELECT * FROM feedback_auditoria", engine)
        df = pd.merge(df_transacoes, df_feedbacks, left_on="id", right_on="id_transacao", how="inner")

        df["data"] = pd.to_datetime(df["data"])
        df["dia_semana"] = df["data"].dt.weekday
        df["hora"] = df["data"].dt.hour
        df["tem_justificativa"] = df["justificativa"].notna().astype(int)

        X = df[["valor_transacao", "dia_semana", "hora", "tem_justificativa"]]
        y = df["rotulo"]

        modelo = RandomForestClassifier(n_estimators=100, random_state=42)
        modelo.fit(X, y)

        joblib.dump(modelo, "modelo_auditai.pkl")

        return {"mensagem": "Feedback salvo e modelo reentreinado com sucesso.", "feedback_id": feedback.id_transacao, "amostras_usadas": len(df)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/ia_auditoria")
def treinar_modelo_ia():
    try:
        df = pd.read_sql("SELECT * FROM transacoes", engine)
        feedbacks = pd.read_sql("SELECT * FROM feedback_auditoria", engine)
        df = pd.merge(df, feedbacks, left_on="id", right_on="id_transacao", how="inner")
        df["data"] = pd.to_datetime(df["data"])
        df["dia_semana"] = df["data"].dt.weekday
        df["hora"] = df["data"].dt.hour
        df["tem_justificativa"] = df["justificativa"].notna().astype(int)
        X = df[["valor_transacao", "dia_semana", "hora", "tem_justificativa"]]
        y = df["rotulo"]
        modelo = RandomForestClassifier(n_estimators=100, random_state=42)
        modelo.fit(X, y)
        joblib.dump(modelo, "modelo_auditai.pkl")
        return {"mensagem": "Modelo treinado e salvo com sucesso.", "quantidade_amostras": len(df)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/ia_prever")
def prever_ia(transacao: TransacaoIA):
    try:
        if not os.path.exists("modelo_auditai.pkl"):
            raise HTTPException(status_code=400, detail="Modelo IA não treinado.")
        modelo = joblib.load("modelo_auditai.pkl")
        data = pd.to_datetime(transacao.data)
        entrada = pd.DataFrame([{
            "valor_transacao": transacao.valor_transacao,
            "dia_semana": data.weekday(),
            "hora": data.hour,
            "tem_justificativa": int(bool(transacao.justificativa))
        }])
        predicao = modelo.predict(entrada)[0]
        return {"previsao": predicao}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/risco")
def cadastrar_risco(risco: Risco):
    try:
        query = text("""
            INSERT INTO riscos (titulo, descricao, categoria, probabilidade, impacto, status)
            VALUES (:titulo, :descricao, :categoria, :probabilidade, :impacto, :status)
        """)
        # Garante que a transação será efetivada com commit()
        with engine.connect() as conn:
            with conn.begin():  # <- este bloco garante o commit automático
                conn.execute(query, risco.dict())
        return {"mensagem": "Risco cadastrado com sucesso."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao cadastrar risco: {str(e)}")


@app.get("/riscos")
def listar_riscos():
    try:
        df = pd.read_sql("SELECT * FROM riscos", engine)
        return df.to_dict(orient="records")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/controle")
def cadastrar_controle(controle: Controle):
    try:
        query = text("""
            INSERT INTO controles (id_risco, nome, tipo, descricao, eficacia, responsavel)
            VALUES (:id_risco, :nome, :tipo, :descricao, :eficacia, :responsavel)
        """)
        with engine.connect() as conn:
            conn.execute(query, controle.dict())
        return {"mensagem": "Controle cadastrado com sucesso."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/controles")
def listar_controles():
    try:
        df = pd.read_sql("SELECT * FROM controles", engine)
        return df.to_dict(orient="records")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
