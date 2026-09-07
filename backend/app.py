import json
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
    cores_validas = cmd['identidade_cor'] if cmd['identidade_cor'] else ["Incolor (C)"]

    system_instruction = f"""
    Você é um especialista em Magic: The Gathering (Commander/EDH).
    Identidade de Cor Permitida: {cores_validas}. É PROIBIDO incluir cartas fora dessas cores.
    Gere EXATAMENTE 63 cartas únicas de mágicas e terrenos não-básicos.
    """

    prompt = f"""
    Gere a decklist para **{cmd['nome']}** e a análise tática.

    RESTRIÇÕES DO BARALHO:
    - Comandante: {cmd['nome']}
    - Cores permitidas: {cores_validas}
    - Orçamento: ${orcamento} USD
    - Nível de Poder: {nivel_poder}
    - Subtema: {subtema}
    - Regras Extras: {regras_extras}
    - Sugestões EDHREC: {edhrec_cards}

    ESTRUTURA OBRIGATÓRIA DA RESPOSTA:

    1. Na primeira linha, retorne o peso de cada cor nas mágicas escolhidas em formato JSON:
    {{"PROPORCAO": {{"G": 40, "U": 30, "B": 30}}}}

    2. DECKLIST:
    1 {cmd['nome']}
    1 Sol Ring
    (Gere mais 62 cartas não-terrenos e terrenos não-básicos no formato '1 Nome da Carta')
    NÃO inclua terrenos básicos nesta lista.

    3. ANÁLISE TÁTICA:
    Após a última carta, dê duas quebras de linha e adicione o cabeçalho '### 🧠 PLANO DE JOGO E COMBOS'.
    """

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3
        )
        
        texto_original = response.choices[0].message.content

        # 1. Extração do JSON de proporção de cores
        pesos_cor = {}
        match_json = re.search(r'\{"PROPORCAO":\s*\{.*?\}\}', texto_original)
        if match_json:
            try:
                pesos_cor = json.loads(match_json.group(0)).get("PROPORCAO", {})
            except Exception:
                pesos_cor = {}

        # 2. Separação entre a lista e a análise
        partes = texto_original.split("### 🧠 PLANO DE JOGO E COMBOS")
        bloco_deck = partes[0].strip()
        analise = "### 🧠 PLANO DE JOGO E COMBOS" + partes[1] if len(partes) > 1 else ""

        # Isolamento das linhas de cartas (removendo JSON/comentários)
        linhas_cartas = [
            l.strip() for l in bloco_deck.split("\n") 
            if l.strip() and l.strip().startswith("1 ") and not l.strip().startswith("{")
        ]
        
        # Limita o bloco de não-básicas a exatamente 64 cartas (Comandante + 63)
        linhas_cartas = linhas_cartas[:64]
        terrenos_necessarios = 100 - len(linhas_cartas)

        # 3. Cálculo proporcional de terrenos básicos
        mapa_terrenos = {'G': 'Forest', 'U': 'Island', 'B': 'Swamp', 'R': 'Mountain', 'W': 'Plains', 'C': 'Wastes'}
        terrenos_gerados = []

        if pesos_cor and terrenos_necessarios > 0:
            total_peso = sum(pesos_cor.values()) or 1
            acumulado = 0
            itens_cor = list(pesos_cor.items())
            
            for idx, (cor, peso) in enumerate(itens_cor):
                if idx == len(itens_cor) - 1:
                    qtd = terrenos_necessarios - acumulado
                else:
                    qtd = round((peso / total_peso) * terrenos_necessarios)
                    acumulado += qtd
                
                nome_terreno = mapa_terrenos.get(cor, 'Wastes')
                if qtd > 0:
                    terrenos_gerados.append(f"{qtd} {nome_terreno}")
        else:
            terrenos_gerados.append(f"{terrenos_necessarios} Wastes")

        # 4. Formatação final limpa para importação
        decklist_final = "\n".join(linhas_cartas) + "\n" + "\n".join(terrenos_gerados)
        resultado_formatado = f"{decklist_final}\n\n{analise}"

        return jsonify(
            {
                "comandante": cmd["nome"],
                "cores": cmd["identidade_cor"],
                "resultado": resultado_formatado,
            }
        )
    except Exception as e:
        return jsonify({"error": f"Erro ao gerar deck com OpenAI: {str(e)}"}), 500


if __name__ == "__main__":
    app.run(debug=True, port=5000)
