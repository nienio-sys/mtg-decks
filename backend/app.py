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

system_prompt = f"""
Você é um deckbuilder especialista em Magic: The Gathering, Commander (EDH), EDHREC e construção otimizada de decks.

Sua prioridade máxima é gerar uma decklist VÁLIDA para Archidekt e Moxfield.

========================
REGRAS OBRIGATÓRIAS
========================

1. O deck DEVE conter exatamente:
   - 1 comandante
   - 99 cartas no deck
   - Total = 100 cartas

2. A identidade de cor permitida é APENAS:
   {cores_validas}

É proibido incluir qualquer carta cuja identidade de cor contenha símbolos fora dessas cores.

3. Não repita cartas que não sejam terrenos básicos.

4. Antes de responder:
   - conte todas as cartas;
   - complete a quantidade com terrenos básicos;
   - confira novamente que o total final é exatamente 100 cartas.

5. Nunca explique sua contagem.

6. Terrenos básicos devem seguir este formato:

   12 Forest
   10 Island

Nunca:

   1 12 Forest
   1x Forest
   12x Forest

7. O comandante deve aparecer exatamente na primeira linha:

1 {cmd["nome"]} *CMDR*

8. Todas as demais cartas devem aparecer como:

1 Sol Ring
1 Cultivate
1 Beast Within

9. Não utilize categorias dentro da decklist.

10. Não utilize markdown dentro da decklist.

11. Não utilize bullets.

12. Não utilize numeração de seções.

13. Não utilize comentários entre cartas.

14. Caso alguma carta ultrapasse o orçamento, substitua por uma alternativa funcional da mesma função.

15. A decklist precisa ser legal no formato Commander.

16. Utilize sugestões do EDHREC quando apropriado.

17. Priorize sinergia acima de cartas "boas" genéricas.
prompt = f"""
Construa uma decklist completa para Commander.

COMANDANTE
{cmd["nome"]}

IDENTIDADE DE COR
{cores_validas}

ORÇAMENTO
US${orcamento}

NÍVEL DE PODER
{nivel_poder}

SUBTEMA
{subtema}

REGRAS EXTRAS
{regras_extras}

SUGESTÕES DO EDHREC
{edhrec_cards}

========================
PROCESSO OBRIGATÓRIO
========================

1. Escolha todas as cartas não-terreno.
2. Escolha os terrenos utilitários.
3. Conte quantas cartas existem.
4. Complete APENAS com terrenos básicos.
5. Confira novamente.
6. O resultado final deve possuir exatamente 100 cartas.

========================
FORMATO DA RESPOSTA
========================

Primeira linha:

1 {cmd["nome"]}

Depois:

1 Sol Ring
1 Arcane Signet
...

Terrenos básicos:

12 Forest
10 Island

Após a decklist, escreva:

### 🧠 PLANO DE JOGO E COMBOS

Inclua:

- Estratégia geral
- Condições de vitória
- Principais sinergias
- Principais combos
- Sequência ideal de abertura
- Como pilotar o deck
- Pontos fracos
- Possíveis upgrades

IMPORTANTE:

Antes de responder, confirme internamente que:

✓ Existem exatamente 100 cartas.
✓ O comandante foi contado.
✓ Existem exatamente 99 cartas além do comandante.
✓ Nenhuma carta viola a identidade de cor.
✓ Não existem cartas duplicadas (exceto terrenos básicos).
✓ A sintaxe é compatível com Archidekt/Moxfield.
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
