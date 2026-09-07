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

    # Tratamento para exibir a identidade de cor de forma clara
    cores_validas = cmd['identidade_cor'] if cmd['identidade_cor'] else ["Incolor (C)"]

    system_instruction = f"""
    Você é um especialista em Magic: The Gathering e no formato Commander (EDH).
    
    REGRA INVIOLÁVEL DE IDENTIDADE DE COR:
    1. A contagem TOTAL exata do deck DEVE ser de 100 cartas (1 Comandante + 99 cartas no 99).
    2. Identidade de Cor permitida: {cores_validas}. NENHUMA carta fora dessas cores pode entrar.
    3. Para terrenos básicos, NUNCA coloque o número '1' na frente da quantidade. 
       - ERRADO: "1 5 Forest" ou "1 5x Forest"
       - CORRETO: "5 Forest"
    4. Siga a sintaxe exata do Archidekt/Moxfield para a lista de cartas.
    """

    prompt = f"""
   Gere uma Decklist completa de 100 cartas para **{cmd['nome']}** seguida por uma análise tática.
    
    RESTRIÇÕES DO BARALHO:
    - Comandante: {cmd['nome']}
    - Identidade de Cor Permitida: {cores_validas}
    - Orçamento Máximo: ${orcamento} USD
    - Nível de Poder: {nivel_poder}
    - Subtema / Arquétipo Exigido: {subtema}
    - Regras Extras do Jogador: {regras_extras}
    - Sugestões EDHREC: {edhrec_cards}
    
    REGRAS RÍGIDAS DE FORMATAÇÃO DA DECKLIST (COMPATÍVEL COM ARCHIDEKT/MOXFIELD):
    1. A lista de cartas DEVE ser um bloco limpo, sem marcas de markdown (#, ##, **), sem linhas em branco extras e sem subtítulos de categoria dentro do bloco principal de cartas.
    2. Coloque apenas o Comandante na primeira linha com a tag de comandante: '1 {cmd["nome"]}
    3. Para cartas únicas, use SEMPRE o formato '1 Nome da Carta' (ex: '1 Sol Ring').
    4. Para terrenos básicos, use SEMPRE o formato 'QTD Nome do Terreno' (ex: '8 Forest', '5 Swamp').
    5. NÃO adicione prefixo ou caracteres especiais antes dos nomes ou depois dos nomes, nem espaços desnecessários.
    
    EXEMPLO DE FORMATAÇÃO EXIGIDO PARA A DECKLIST:
    1 {cmd['nome']} *CMDR*
    1 Sol Ring
    1 Arcane Signet
    1 Command Tower
    5 Forest
    5 Island
    5 Swamp
    (Continue até a soma das quantidades ser exatamente 100 cartas).
    
    ESTRUTURA DA RESPOSTA:
    - Inicie direto com as 100 cartas do deck (uma por linha).
    - Após a última carta, adicione duas quebras de linha e coloque o cabeçalho '### 🧠 PLANO DE JOGO E COMBOS' para a análise tática.
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
