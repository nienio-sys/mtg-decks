import os
import re
import requests
from flask import Flask, jsonify, request
from flask_cors import CORS
from openai import OpenAI

app = Flask(__name__)
CORS(app)

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
        return [c.get("name") for c in resposta.json().get("cardlist", [])[:15]]
    return []


@app.route("/", methods=["GET"])
def home():
    return jsonify({"status": "online", "message": "API do Commander Deckbuilder está rodando com sucesso!"}), 200


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
    cores_validas = cmd["identidade_cor"] if cmd["identidade_cor"] else ["Incolor (C)"]

    system_instruction = """
Você é um especialista em Magic: The Gathering e Commander (EDH).

Construa decks válidos, consistentes e compatíveis com Archidekt/Moxfield.

REGRAS:
- Exatamente 100 cartas incluindo o comandante.
- O comandante aparece apenas uma vez.
- Não repetir cartas, exceto terrenos básicos.
- Respeitar identidade de cores informada.
- Respeitar orçamento.
- Priorizar sinergia, curva de mana, ramp, compra e remoções.

FORMATO:
- Sem markdown na decklist.
- Sem títulos ou comentários.
- Primeira linha: 1 Nome do Comandante
- Demais: 1 Nome da Carta
- Básicos: QTD Nome do Terreno

Antes de responder valide:
- 100 cartas;
- identidade de cores;
- sem duplicatas (exceto básicos);
- comandante apenas uma vez.
"""

    prompt = f"""
Gere uma decklist de Commander (EDH).

Parâmetros:
- Comandante: {cmd['nome']}
- Identidade de cores: {cores_validas}
- Orçamento máximo: USD {orcamento}
- Nível de poder: {nivel_poder}
- Subtema: {subtema}
- Regras extras: {regras_extras}
- Sugestões EDHREC (priorize quando possível): {", ".join(edhrec_cards)}
- NÃO adicione prefixo ou caracteres especiais antes ou depois dos nomes, nem espaços desnecessários.

Após a decklist, deixe duas linhas e escreva exatamente:

### 🧠 PLANO DE JOGO E COMBOS

Explique:
- Plano de jogo
- Sinergias
- Condições de vitória
- Combos
- Sequência ideal
- Pontos fortes
- Pontos fracos
- Upgrades
"""

    try:
        response = client.chat.completions.create(
            model="gpt-5-mini",
            messages=[
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": prompt},
            ],
            temperature=0.3,
        )

        return jsonify({
            "comandante": cmd["nome"],
            "cores": cmd["identidade_cor"],
            "resultado": response.choices[0].message.content,
        })

    except Exception as e:
        return jsonify({"error": f"Erro ao gerar deck com OpenAI: {e}"}), 500


if __name__ == "__main__":
    app.run(debug=True, port=5000)
