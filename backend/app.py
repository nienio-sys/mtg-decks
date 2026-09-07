import json
import re

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
    Você é um gerador técnico de baralhos de Magic: The Gathering (Commander/EDH).
    Identidade de Cor Permitida: {cores_validas}. NUNCA inclua cartas fora dessas cores.
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
    
    1. PROPORCAO_CORES:
    Retorne um JSON na primeira linha calculando a proporção aproximada de cada cor nas 63 mágicas selecionadas (soma total = 100).
    Exemplo para deck Tricolor (G/U/B):
    {{"PROPORCAO": {{"G": 50, "U": 30, "B": 20}}}}
    (Se for incolor, use {{"PROPORCAO": {{"C": 100}}}})

    2. DECKLIST:
    1 {cmd['nome']} *CMDR*
    1 Sol Ring
    (Gere exatamente mais 62 cartas não-terrenos e terrenos não-básicos no formato '1 Nome da Carta')
    NÃO adicione terrenos básicos aqui.

    3. ANÁLISE:
    Após a última carta, dê duas quebras de linha e coloque o cabeçalho '### 🧠 PLANO DE JOGO E COMBOS'.
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

        # 1. EXTRAÇÃO DO PESO DE CORES (JSON)
        pesos_cor = {}
        match_json = re.search(r'\{"PROPORCAO":\s*\{.*?\}\}', texto_original)
        if match_json:
            try:
                pesos_cor = json.loads(match_json.group(0)).get("PROPORCAO", {})
            except:
                pesos_cor = {}

        # 2. SEPARAÇÃO DA LISTA E ANÁLISE
        partes = texto_original.split("### 🧠 PLANO DE JOGO E COMBOS")
        bloco_deck = partes[0].strip()
        analise = "### 🧠 PLANO DE JOGO E COMBOS" + partes[1] if len(partes) > 1 else ""

        # Extrai apenas as linhas de cartas válidas (ignorando o JSON inicial)
        linhas_cartas = [
            l.strip() for l in bloco_deck.split("\n") 
            if l.strip() and l.strip().startswith("1 ") and not l.strip().startswith("{")
        ]
        
        # Garante exatamente 64 cartas no bloco de mágicas (Comandante + 63)
        linhas_cartas = linhas_cartas[:64]
        total_atuais = len(linhas_cartas)
        terrenos_necessarios = 100 - total_atuais

        # 3. CÁLCULO PROPORCIONAL DOS TERRENOS BÁSICOS
        mapa_terrenos = {'G': 'Forest', 'U': 'Island', 'B': 'Swamp', 'R': 'Mountain', 'W': 'Plains', 'C': 'Wastes'}
        terrenos_gerados = []

        if pesos_cor and terrenos_necessarios > 0:
            total_peso = sum(pesos_cor.values()) or 1
            acumulado = 0
            
            # Converte porcentagem do peso de mana em quantidade exata de terrenos
            itens_cor = list(pesos_cor.items())
            for idx, (cor, peso) in enumerate(itens_cor):
                if idx == len(itens_cor) - 1:
                    qtd = terrenos_necessarios - acumulado  # Sobra final para fechar exato
                else:
                    qtd = round((peso / total_peso) * terrenos_necessarios)
                    acumulado += qtd
                
                nome_terreno = mapa_terrenos.get(cor, 'Wastes')
                if qtd > 0:
                    terrenos_gerados.append(f"{qtd} {nome_terreno}")
        else:
            # Fallback caso a IA não envie o JSON
            terrenos_gerados.append(f"{terrenos_necessarios} Wastes")

        # 4. MONTAGEM DA RESPOSTA FINAL (COMPATÍVEL COM ARCHIDEKT)
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
