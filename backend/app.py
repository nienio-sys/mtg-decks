import os
import re
import requests
from flask import Flask, jsonify, request
from flask_cors import CORS
from google import genai

app = Flask(__name__)
CORS(app)  # Permite que seu frontend (Vercel) converse com o backend

# Busca a chave API configurada nas variáveis de ambiente do Render
api_key = os.environ.get("GEMINI_API_KEY")
client = genai.Client(api_key=api_key) if api_key else None


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

# Adicione esta rota logo acima de @app.route("/api/gerar-deck")

@app.route("/", methods=["GET"])
def home():
    return jsonify({
        "status": "online",
        "message": "API do Commander Deckbuilder está rodando com sucesso!"
    }), 200


@app.route("/api/gerar-deck", methods=["POST"])
def gerar_deck():
    if not client:
        return jsonify({"error": "Chave GEMINI_API_KEY não configurada no servidor."}), 500

    dados = request.json or {}
    comandante = dados.get("comandante")
    orcamento = dados.get("orcamento", 150)
    nivel_poder = dados.get("nivel_poder", "Casual")

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
    - Sugestões EDHREC: {edhrec_cards}
    
    ESTRUTURA DA RESPOSTA:
    1. DECKLIST (Exatamente 100 cartas no formato '1 Nome da Carta' divididas por categoria).
    2. RESUMO ESTRATÉGICO E COMBOS (Cabeçalho '### 🧠 PLANO DE JOGO E COMBOS' com Plano de Jogo, Combos e Condição de Vitória).
    """

    try:
        response = client.models.generate_content(
            model="gemini-3.6-flash", contents=prompt
        )
        return jsonify(
            {
                "comandante": cmd["nome"],
                "cores": cmd["identidade_cor"],
                "resultado": response.text,
            }
        )
    except Exception as e:
        return jsonify({"error": f"Erro ao gerar deck com Gemini: {str(e)}"}), 500


if __name__ == "__main__":
    app.run(debug=True, port=5000)
