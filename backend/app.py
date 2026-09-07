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


def procurar_cardlist(obj):
    """
    Procura recursivamente qualquer chave 'cardlist'
    dentro do JSON do EDHREC.
    """
    if isinstance(obj, dict):
        for chave, valor in obj.items():
            if chave == "cardlist" and isinstance(valor, list):
                return valor

            resultado = procurar_cardlist(valor)
            if resultado:
                return resultado

    elif isinstance(obj, list):
        for item in obj:
            resultado = procurar_cardlist(item)
            if resultado:
                return resultado

    return None


def obter_recomendacoes_edhrec(nome_comandante):
    slug = re.sub(
        r"[\s_]+",
        "-",
        re.sub(r"[^\w\s-]", "", nome_comandante.lower())
    )

    url = f"https://json.edhrec.com/pages/commanders/{slug}.json"

    try:
        resposta = requests.get(
            url,
            headers={"User-Agent": "DeckbuilderWeb/1.0"},
            timeout=15
        )

        if resposta.status_code != 200:
            return []

        dados = resposta.json()

        cards = procurar_cardlist(dados)

        if not cards:
            print("Nenhum cardlist encontrado no EDHREC.")
            return []

        recomendacoes = []
        vistos = set()

        for carta in cards:

            nome = carta.get("name")

            if not nome:
                continue

            if nome in vistos:
                continue

            vistos.add(nome)

            synergy = carta.get("synergy")

            if synergy is not None:
                recomendacoes.append(
                    f"{nome} (Synergy {synergy})"
                )
            else:
                recomendacoes.append(nome)

        print(f"EDHREC: {len(recomendacoes)} cartas carregadas.")

        return recomendacoes[:60]

    except Exception as e:
        print("Erro EDHREC:", e)
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
CONSTRUÇÃO DA BASE DE MANA

A base de mana deve ser otimizada para Commander.

Regras obrigatórias:

- Priorize terrenos não básicos sempre que houver opções compatíveis com o orçamento.
- Utilize Command Tower sempre que possível.
- Para decks de 2 ou mais cores, priorize terrenos que gerem múltiplas cores.
- Utilize terrenos utilitários que tenham sinergia com o comandante ou estratégia quando apropriado.
- Complete a base de mana com terrenos básicos apenas quando necessário para garantir consistência.
- Evite gerar decks compostos majoritariamente por terrenos básicos quando existirem alternativas melhores dentro do orçamento.

Considere, quando apropriado:
- Fetch Lands
- Shock Lands
- Check Lands
- Pain Lands
- Fast Lands
- Slow Lands
- Bond Lands
- Filter Lands
- Triomes
- Surveil Lands
- Battlebond Lands
- Pathways
- Channel Lands
- Creature Lands
- Command Tower
- Exotic Orchard
- Reflecting Pool
- Path of Ancestry
- Plaza of Heroes
- Cavern of Souls
- Boseiju, Who Endures
- Otawara, Soaring City
- Takenuma, Abandoned Mire
- Eiganjo, Seat of the Empire
- Sokenzan, Crucible of Defiance

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
- Cartas mais recomendadas pelo EDHREC: {chr(10).join("- " + c for c in edhrec_cards)}
- NÃO adicione prefixo ou caracteres especiais antes ou depois dos nomes, nem espaços desnecessários.
- Para orçamentos abaixo de US$100, utilize terrenos econômicos.
- Para orçamentos entre US$100 e US$300, utilize uma base de mana intermediária.
- Para orçamentos acima de US$300, utilize a melhor base de mana possível.

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
