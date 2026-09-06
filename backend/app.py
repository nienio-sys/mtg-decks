import os
import re
import requests
from flask import Flask, jsonify, request
from flask_cors import CORS
from openai import OpenAI

app = Flask(__name__)
CORS(app)

# Busca a chave API configurada nas variáveis de ambiente do Render
api_key = os.environ.get("OPENAI_API_KEY")
client = OpenAI(api_key=api_key) if api_key else None


def obter_dados_comandante(nome_carta):
    url = "https://api.scryfall.com/cards/named"
    resposta = requests.get(
        url,
        params={"fuzzy": nome_carta},
        headers={"User-Agent": "DeckbuilderWeb/1.0"},
    )
    if resposta.status_code == 200:
        carta = resposta.json()
        return {
            "nome": carta.get("name"),
            "mana_cost": carta.get("mana_cost", "N/A"),
            "tipo": carta.get("type_line"),
            "identidade_cor": carta.get("color_identity"),
            "texto_oracle": carta.get("oracle_text", ""),
        }
    return None


def obter_recomendacoes_edhrec(nome_comandante):
    slug = re.sub(r"[\s_]+", "-", re.sub(r"[^\w\s-]", "", nome_comandante.lower()))
    url = f"https://json.edhrec.com/pages/commanders/{slug}.json"
    resposta = requests.get(url, headers={"User-Agent": "DeckbuilderWeb/1.0"})
    if resposta.status_code == 200:
        container = resposta.json().get("cardlist", [])
        return [c.get("name") for c in container[:15]]
    return []


@app.route("/", methods=["GET"])
def home():
    return jsonify({
        "status": "online",
        "message": "API do Commander Deckbuilder está rodando com sucesso!"
    }), 200


@app.route("/api/gerar-deck", methods=["POST"])
def gerar_deck():
    if not client:
        return jsonify({"error": "Chave OPENAI_API_KEY não configurada no servidor."}), 500

    dados = request.json or {}
    comandante = dados.get("comandante")
    orcamento = dados.get("orcamento", 150)
    nivel_poder = dados.get("nivel_poder", "Casual")
    subtema = dados.get("subtema", "Sinergia Geral do Comandante")
    regras_extras = dados.get("regras_extras", "Nenhuma")

    if not comandante:
        return jsonify({"error": "Nome do comandante é obrigatório."}), 400

    cmd = obter_dados_comandante(comandante)
    if not cmd:
        return jsonify({"error": "Comandante não encontrado no Scryfall."}), 404

    edhrec_cards = obter_recomendacoes_edhrec(cmd["nome"])

    prompt = f"""
    Você é um especialista em Commander (EDH).
    Gere uma Decklist completa de 100 cartas para **{cmd['nome']}** seguida por uma análise tática.
    
    RESTRIÇÕES:
    - Identidade de Cor: {cmd['identidade_cor']}
    - Orçamento Máximo: ${orcamento} USD
    - Nível de Poder: {nivel_poder}
    - Subtema / Arquétipo Exigido: {subtema}
    - Regras Extras / Restrições do Jogador: {regras_extras}
    - Sugestões EDHREC: {edhrec_cards}
    
    ESTRUTURA DA RESPOSTA:
    1. DECKLIST (Exatamente 100 cartas no formato '1 Nome da Carta' divididas por categoria).
    2. RESUMO ESTRATÉGICO E COMBOS (Cabeçalho '### 🧠 PLANO DE JOGO E COMBOS' detalhando a execução focada no subtema '{subtema}' e respeitando todas as regras extras).
    """

    try:
        # Chamada utilizando a SDK oficial da OpenAI (GPT-4o-mini ou GPT-4o)
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Você é um assistente especializado na montagem e análise estratégica de baralhos do formato Commander de Magic: The Gathering."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7
        )
        
        resultado_texto = response.choices[0].message.content

        return jsonify(
            {
                "comandante": cmd["nome"],
                "cores": cmd["identidade_cor"],
                "resultado": resultado_texto,
            }
        )
    except Exception as e:
        return jsonify({"error": f"Erro ao gerar deck com OpenAI: {str(e)}"}), 500


if __name__ == "__main__":
    app.run(debug=True, port=5000)
