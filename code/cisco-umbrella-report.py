#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import requests
import time
import csv
import calendar
from datetime import datetime, timedelta
import json
import base64 # Importa o módulo base64 para decodificação de JWT

# =============================
# CONSTANTES / ENDPOINTS PARA CISCO UMBRELLA
# =============================
# URL base para a API de Relatórios v2 do Umbrella
UMBRELLA_REPORTS_API_BASE = "https://reports.api.umbrella.com/v2"
# URL para autenticação na API de Gerenciamento do Umbrella (para obter o token)
UMBRELLA_AUTH_URL = "https://management.api.umbrella.com/auth/v2/oauth2/token"
# Template do Endpoint para buscar atividades na API de Relatórios v2 do Umbrella.
# O {org_id} será preenchido dinamicamente.
UMBRELLA_ACTIVITY_ENDPOINT_TEMPLATE = f"{UMBRELLA_REPORTS_API_BASE}/organizations/{{org_id}}/activity"

# =============================
# UTILITÁRIOS DE TEMPO
# =============================
def dt_to_epoch_millis(dt: datetime) -> int:
    """
    Converte datetime NAIVE (interpretado como hora local) para epoch em milissegundos.
    Mantém o comportamento que funcionava antes (equivalente a time.mktime).
    """
    return int(time.mktime(dt.timetuple()) * 1000)

def fmt_dt(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S")

def elapsed(start_ts: float) -> str:
    return str(timedelta(seconds=int(time.time() - start_ts)))

# =============================
# RATE LIMITER (MÁX 1000/HORA PARA UMBRELLA)
# =============================
class RateLimiter:
    def __init__(self, max_requests=1000, per_seconds=3600):
        self.max_requests = max_requests
        self.per_seconds = per_seconds
        self.window_start = time.time()
        self.count = 0

    def check(self):
        now = time.time()
        # reset da janela se passou 1h
        if now - self.window_start >= self.per_seconds:
            self.window_start = now
            self.count = 0

        if self.count >= self.max_requests:
            wait = int(self.per_seconds - (now - self.window_start))
            if wait < 0:
                wait = 0
            print(f"\n⏸️ Rate limit atingido ({self.max_requests}/hora). Aguardando {wait}s...")
            time.sleep(wait)
            self.window_start = time.time()
            self.count = 0

        self.count += 1

# =============================
# AUTENTICAÇÃO
# =============================
def get_token(client_id: str, client_secret: str) -> str:
    """
    Obtém um token de acesso usando a chave e o segredo da API do Umbrella.
    """
    resp = requests.post(
        UMBRELLA_AUTH_URL,
        data={"grant_type": "client_credentials"},
        auth=(client_id, client_secret),
        timeout=30
    )
    resp.raise_for_status()
    return resp.json()["access_token"]

def decode_jwt_payload(jwt_token: str) -> dict | None:
    """
    Decodifica o payload de um JWT.
    """
    try:
        payload_encoded = jwt_token.split('.')[1]
        # Adiciona padding se necessário para decodificação Base64 URL-safe
        padding_needed = len(payload_encoded) % 4
        if padding_needed:
            payload_encoded += '=' * (4 - padding_needed)
            
        payload_decoded = base64.urlsafe_b64decode(payload_encoded).decode('utf-8')
        return json.loads(payload_decoded)
    except Exception as e:
        print(f"❌ Erro ao decodificar o payload do JWT: {e}")
        return None

def prompt_credentials_with_test() -> tuple[str, str, str, str]:
    """
    Pede CHAVE_API/SEGREDO_API, obtém um token válido e extrai o ORG_ID do JWT.
    Retorna (client_id, client_secret, token, org_id).
    """
    while True:
        client_id = input("🔑 Chave da API do Umbrella (CLIENT_ID): ").strip()
        client_secret = input("🔑 Segredo da API do Umbrella (CLIENT_SECRET): ").strip()
        
        try:
            token = get_token(client_id, client_secret)
            print("✅ Autenticação OK. Decodificando token para obter ORG_ID...")
            
            jwt_payload = decode_jwt_payload(token)
            if jwt_payload and 'sub' in jwt_payload and isinstance(jwt_payload['sub'], str):
                sub_parts = jwt_payload['sub'].split('/')
                if len(sub_parts) >= 2 and sub_parts[0] == 'org':
                    org_id = sub_parts[1]
                    print(f"🎉 ORG_ID extraído do token: {org_id} 🎉\n")
                    return client_id, client_secret, token, org_id
                else:
                    print("⚠️ Não foi possível extrair o ORG_ID do campo 'sub' do token. Formato inesperado.")
            else:
                print("⚠️ Não foi possível decodificar o token ou o campo 'sub' está ausente/inválido.")
            
            print("Tente novamente com credenciais válidas que permitam a extração do ORG_ID.\n")

        except requests.HTTPError as e:
            msg = ""
            try:
                msg = e.response.text[:200]
            except Exception:
                pass
            print(f"❌ Falha na autenticação ({e}). Detalhe: {msg}")
            print("Certifique-se de que a Chave e o Segredo da API estão corretos e têm as permissões necessárias (Reports/Granular Events: Read-Only). Tente novamente.\n")
        except Exception as e:
            print(f"❌ Erro inesperado ao obter token ou decodificar: {e}")
            print("Tente novamente.\n")

# =============================
# PROMPT INTERATIVO DE DATA
# =============================
def interactive_prompt_dates() -> tuple[int, int, list[int]]:
    anos = [datetime.now().year, datetime.now().year - 1, datetime.now().year - 2, datetime.now().year - 3, datetime.now().year - 4]
    print("Selecione o ano:")
    for i, a in enumerate(anos, 1):
        print(f"{i}. {a}")
    while True:
        try:
            ano_idx = int(input("Ano (número): "))
            if 1 <= ano_idx <= len(anos):
                ano = anos[ano_idx - 1]
                break
        except ValueError:
            pass
        print("Entrada inválida. Tente novamente.")
    meses = ["janeiro","fevereiro","março","abril","maio","junho",
             "julho","agosto","setembro","outubro","novembro","dezembro"]
    print("\nSelecione o mês:")
    for i, m in enumerate(meses, 1):
        print(f"{i}. {m}")
    while True:
        try:
            mes = int(input("Mês (número): "))
            if 1 <= mes <= 12:
                break
        except ValueError:
            pass
        print("Entrada inválida. Tente novamente.")
    max_dia = calendar.monthrange(ano, mes)[1]
    print("\nSelecione o dia:")
    print("0. Todos os dias do mês")
    while True:
        try:
            dia = int(input("Dia (número ou 0): "))
            if 0 <= dia <= max_dia:
                break
        except ValueError:
            pass
        print("Entrada inválida. Tente novamente.")
    dias = list(range(1, max_dia + 1)) if dia == 0 else [dia]
    return ano, mes, dias

# =============================
# DOWNLOAD DE JANELA COM PAGINAÇÃO
# =============================
def fetch_activity_window(
    token: str,
    client_id: str,
    client_secret: str,
    org_id: str, # org_id agora é passado para construir a URL
    from_ts: int,
    to_ts: int,
    limit: int = 1000,
    offset_ceiling: int | None = None,
    verbose: bool = False,
    rate_limiter: RateLimiter | None = None
) -> tuple[list[dict], bool, str]:
    """
    Busca eventos entre from_ts e to_ts (epoch ms), paginando por offset.
    Retorna (eventos, need_minute_fallback, token_atualizado).
    Ativa fallback minuto-a-minuto se:
      - HTTP 400/404; ou
      - offset >= offset_ceiling (Ex.: 10000 para Umbrella Activity Search).
    Faz retry de rede com backoff e renova token em 403 (até 5x).
    """
    offset = 0
    events: list[dict] = []
    need_minute_fallback = False

    consecutive_403 = 0
    max_403_attempts = 5
    max_retries_conn = 5

    # Constrói o endpoint da API com o ID da organização
    activity_url = UMBRELLA_ACTIVITY_ENDPOINT_TEMPLATE.format(org_id=org_id)

    while True:
        if offset_ceiling is not None and offset >= offset_ceiling:
            need_minute_fallback = True
            if verbose:
                print(f"   ⚠️ Offset {offset} >= ceiling {offset_ceiling}. Ativando fallback minuto-a-minuto (limite da API).")
            break

        if rate_limiter:
            rate_limiter.check()

        params = {
            "from": str(from_ts),
            "to": str(to_ts),
            "limit": limit,
            "offset": offset
        }
        headers = {"Authorization": f"Bearer {token}"}

        # Retries para erros de conexão/transientes
        resp = None
        for attempt in range(max_retries_conn):
            try:
                resp = requests.get(activity_url, headers=headers, params=params, timeout=60)
                break
            except (requests.exceptions.ConnectionError,
                    requests.exceptions.ChunkedEncodingError,
                    requests.exceptions.ReadTimeout) as e:
                wait = (2 ** attempt)
                print(f"   ⚠️ Erro de conexão ({e}). Tentando novamente em {wait}s...")
                time.sleep(wait)
        if resp is None:
            print("   🚨 Falhas de conexão repetidas. Abortando este intervalo.")
            break

        # Tratamento de retorno
        if resp.status_code == 200:
            try:
                payload = resp.json()
            except Exception as e:
                print(f"   ⚠️ Erro ao decodificar JSON: {e}. Corpo (200 chars): {resp.text[:200]}")
                break

            batch = payload.get("data", [])
            if not batch:
                # sem mais dados
                break

            events.extend(batch)
            offset += len(batch)

            if verbose:
                print(f"      🔹 {len(batch)} eventos (offset agora {offset})")

            consecutive_403 = 0  # reset
            # Se veio menos que limit, acabou a janela
            if len(batch) < limit:
                break

            # continua paginando
            continue

        if resp.status_code == 403:
            consecutive_403 += 1
            print(f"   ⚠️ HTTP 403 detectado ({consecutive_403}/{max_403_attempts}). Renovando token e tentando de novo...")
            try:
                token = get_token(client_id, client_secret)
            except Exception as e:
                print(f"   ❌ Erro ao renovar token: {e}")
                time.sleep(5)  # pequena espera antes de tentar de novo

            if consecutive_403 >= max_403_attempts:
                print("   🚨 403 persistente após várias renovações. Parando este intervalo.")
                break
            # tenta novamente a mesma página
            continue
        
        if resp.status_code == 429:
            wait_time = 60 # O Umbrella bloqueia por 1 hora
            print(f"   🚨 HTTP 429 (Too Many Requests) detectado. Limite de taxa excedido. Aguardando {wait_time}s antes de tentar novamente.")
            time.sleep(wait_time)
            # Tenta novamente a mesma página após a espera
            continue

        if resp.status_code in (400, 404):
            need_minute_fallback = True
            print(f"   ⚠️ HTTP {resp.status_code} — ativando fallback minuto-a-minuto para essa hora. Detalhe: {resp.text[:200]}")
            break

        # Outros erros
        print(f"   ⚠️ HTTP {resp.status_code} retornado. Mensagem: {resp.text[:200]}")
        break

    return events, need_minute_fallback, token

# =============================
# BUSCA DA HORA COM FALLBACK DE MINUTO
# =============================
def fetch_hour_with_minute_fallback(
    token: str,
    client_id: str,
    client_secret: str,
    org_id: str, # org_id agora é passado
    hour_start_dt: datetime,
    limit: int = 1000,
    offset_ceiling: int = 10000,
    verbose: bool = True,
    rate_limiter: RateLimiter | None = None
) -> tuple[list[dict], str]:
    """
    Tenta buscar a hora inteira. Se bater 400/404 ou offset_ceiling,
    cai para minuto-a-minuto (60 chamadas).
    """
    hour_end_dt = hour_start_dt + timedelta(hours=1) - timedelta(milliseconds=1)
    from_ts = dt_to_epoch_millis(hour_start_dt)
    to_ts = dt_to_epoch_millis(hour_end_dt)

    if verbose:
        print(f"\n⏳ Hourly: {fmt_dt(hour_start_dt)} to {fmt_dt(hour_end_dt)}")

    hour_events, need_minute_fallback, token = fetch_activity_window(
        token, client_id, client_secret, org_id, from_ts, to_ts, # Passando org_id
        limit=limit, offset_ceiling=offset_ceiling, verbose=verbose, rate_limiter=rate_limiter
    )

    if not need_minute_fallback:
        if verbose:
            print(f"   ✅ Hour OK: {len(hour_events)} eventos")
        return hour_events, token

    # Fallback minuto-a-minuto
    collected: list[dict] = []
    if verbose:
        print("   ↪️ Iniciando fallback minuto-a-minuto (60 minutos).")
    for m in range(60):
        minute_start = hour_start_dt + timedelta(minutes=m)
        minute_end = minute_start + timedelta(minutes=1) - timedelta(milliseconds=1)
        m_from = dt_to_epoch_millis(minute_start)
        m_to = dt_to_epoch_millis(minute_end)

        if verbose:
            print(f"      ➤ Minute: {fmt_dt(minute_start)} to {fmt_dt(minute_end)} ... ", end="")

        minute_events, _, token = fetch_activity_window(
            token, client_id, client_secret, org_id, m_from, m_to, # Passando org_id
            limit=limit, offset_ceiling=None, verbose=False, rate_limiter=rate_limiter
        )
        collected.extend(minute_events)

        if verbose:
            print(f"{len(minute_events)} events")

    if verbose:
        print(f"   ✅ Fallback minute total: {len(collected)} eventos na hora {hour_start_dt.strftime('%Y-%m-%d %H:00')}")
    return collected, token

# =============================
# CSV
# =============================
def _parse_event_datetime(ev: dict) -> datetime | None:
    """
    Tenta montar um datetime do evento.
    A API do Umbrella geralmente usa 'timestamp' ou 'eventTime' no formato ISO8601.
    """
    ts = ev.get("timestamp")
    if isinstance(ts, str) and ts:
        try:
            return datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except ValueError:
            for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d %H:%M:%S"):
                try:
                    return datetime.strptime(ts, fmt)
                except ValueError:
                    pass
    
    event_time = ev.get("eventTime")
    if isinstance(event_time, str) and event_time:
        try:
            return datetime.fromisoformat(event_time.replace("Z", "+00:00"))
        except ValueError:
            for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d %H:%M:%S"):
                try:
                    return datetime.strptime(event_time, fmt)
                except ValueError:
                    pass
    return None

def save_to_csv(events: list[dict], filename: str):
    """
    Salva incrementalmente. Colunas fixas + evento bruto serializado.
    """
    file_exists = False
    try:
        with open(filename, "r", encoding="utf-8"):
            file_exists = True
    except FileNotFoundError:
        pass

    with open(filename, "a", newline="", encoding="utf-8") as f:
        # Colunas comuns que podem ser extraídas diretamente do Umbrella
        fieldnames = [
            "year", "month", "day", "hour", "timestamp", "eventTime", "identityLabel",
            "internalIp", "externalIp", "destination", "action", "categories",
            "eventType", "protocol", "queryType", "responseCode", "url", "fullEvent"
        ]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()

        for ev in events:
            dt_obj = _parse_event_datetime(ev)
            
            row_data = {
                "year": dt_obj.year if dt_obj else "",
                "month": dt_obj.month if dt_obj else "",
                "day": dt_obj.day if dt_obj else "",
                "hour": dt_obj.hour if dt_obj else "",
                "timestamp": dt_obj.isoformat() if dt_obj else "",
                "eventTime": ev.get("eventTime", ""),
                "identityLabel": ev.get("identity", {}).get("label", ""),
                "internalIp": ev.get("internalIp", ""),
                "externalIp": ev.get("externalIp", ""),
                "destination": ev.get("destination", ""),
                "action": ev.get("action", ""),
                "categories": ", ".join(c.get("label", "") for c in ev.get("categories", [])) if ev.get("categories") else "",
                "eventType": ev.get("eventType", ""),
                "protocol": ev.get("protocol", ""),
                "queryType": ev.get("queryType", ""),
                "responseCode": ev.get("responseCode", ""),
                "url": ev.get("url", ""),
                "fullEvent": str(ev)
            }
            writer.writerow(row_data)

# =============================
# MAIN
# =============================
def main():
    # 1) Credenciais com teste e extração automática do ORG_ID
    client_id, client_secret, token, org_id = prompt_credentials_with_test()

    # 2) Prompt de datas (ano/mês/dia[s])
    ano_relatorio, mes_relatorio, dias_relatorio = interactive_prompt_dates()
    
    # Formato da data de hoje para o nome do arquivo
    hoje = datetime.now()
    data_hoje_str = hoje.strftime("%Y%m%d")

    # Formato da data do relatório para o nome do arquivo
    if len(dias_relatorio) == 1:
        data_relatorio_str = f"{ano_relatorio}{mes_relatorio:02d}{dias_relatorio[0]:02d}"
    else:
        data_relatorio_str = f"{ano_relatorio}{mes_relatorio:02d}"

    # Nome do arquivo CSV no novo padrão
    csv_file = f"cisco-umbrella-{org_id}-{data_hoje_str}-relatoriode-{data_relatorio_str}.csv"
    print(f"\nO arquivo de saída será: {csv_file}")

    start_time = time.time()
    rate_limiter = RateLimiter(max_requests=1000, per_seconds=3600) 

    total = 0
    for idx, dia in enumerate(dias_relatorio):
        print(f"\n📅 Dia: {dia} ({idx+1}/{len(dias_relatorio)})")
        for hour in range(24):
            hour_start = datetime(ano_relatorio, mes_relatorio, dia, hour, 0, 0)
            print(f"⏱️ Tempo decorrido: {elapsed(start_time)}")

            events_hour, token = fetch_hour_with_minute_fallback(
                token, client_id, client_secret, org_id, hour_start, # Passando org_id
                limit=1000,
                offset_ceiling=10000,
                verbose=True,
                rate_limiter=rate_limiter
            )
            print(f"   ✅ Hour OK: {len(events_hour)} eventos")
            save_to_csv(events_hour, csv_file)
            total += len(events_hour)

    print(f"\n🏁 Concluído! {total} eventos salvos em {csv_file}")
    print(f"⏱️ Tempo total: {elapsed(start_time)}")

if __name__ == "__main__":
    main()