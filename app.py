from flask import Flask, render_template_string, request, jsonify
import requests
import networkx as nx
import plotly.graph_objects as go

app = Flask(__name__)

# Solana RPC API
SOLANA_RPC_URL = "https://api.mainnet-beta.solana.com"

# Example high-risk wallets (OFAC, Darknet, etc.)
HIGH_RISK_WALLETS = {"FakeRiskyWallet123", "DarknetVendor456", "OFACBlacklisted789"}

# HTML Template (Embedded)
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Solana AML Monitor</title>
    <style>
        body { font-family: Arial, sans-serif; text-align: center; padding: 20px; }
        input { width: 300px; padding: 10px; }
        button { padding: 10px; margin-left: 10px; cursor: pointer; }
        #graphContainer { margin-top: 20px; width: 100%; height: 500px; }
    </style>
    <script src="https://cdn.plot.ly/plotly-latest.min.js"></script>
</head>
<body>
    <h1>Solana AML Transaction Monitor</h1>
    <input type="text" id="walletInput" placeholder="Enter Solana Wallet Address">
    <button onclick="traceWallet()">Analyze</button>
    <h3 id="riskScore"></h3>
    <div id="graphContainer"></div>
    
    <script>
        function traceWallet() {
            let wallet = document.getElementById("walletInput").value;
            
            fetch("/trace", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ wallet: wallet })
            })
            .then(response => response.json())
            .then(data => {
                if (data.error) {
                    alert(data.error);
                } else {
                    document.getElementById("riskScore").innerText = "Risk Score: " + data.risk_score;
                    Plotly.newPlot(document.getElementById("graphContainer"), JSON.parse(data.graph).data, JSON.parse(data.graph).layout);
                }
            })
            .catch(error => console.error("Error:", error));
        }
    </script>
</body>
</html>
"""

def get_wallet_transactions(wallet_address, limit=10):
    """Fetch recent transactions for a given Solana wallet."""
    payload = {"jsonrpc": "2.0", "id": 1, "method": "getSignaturesForAddress", "params": [wallet_address, {"limit": limit}]}
    response = requests.post(SOLANA_RPC_URL, json=payload)
    return [tx["signature"] for tx in response.json().get("result", [])] if response.status_code == 200 else []

def get_transaction_details(signature):
    """Fetch details for a specific transaction."""
    payload = {"jsonrpc": "2.0", "id": 1, "method": "getTransaction", "params": [signature, "jsonParsed"]}
    response = requests.post(SOLANA_RPC_URL, json=payload)
    return response.json().get("result", {}) if response.status_code == 200 else {}

def extract_transaction_flows(wallet_address, transactions):
    """Extract outgoing transactions and recipient addresses."""
    flow_dict = {}
    total_volume = 0

    for tx in transactions:
        details = get_transaction_details(tx)
        if not details or "transaction" not in details:
            continue

        instructions = details["transaction"]["message"]["instructions"]
        for instruction in instructions:
            if "parsed" in instruction and "info" in instruction["parsed"]:
                parsed = instruction["parsed"]["info"]
                sender = parsed.get("source")
                receiver = parsed.get("destination")
                amount = float(parsed.get("lamports", 0)) / 1e9  # Convert lamports to SOL
                
                if sender == wallet_address and receiver:
                    flow_dict[receiver] = flow_dict.get(receiver, 0) + 1
                    total_volume += amount

    return flow_dict, total_volume

def assign_risk_score(transaction_count, total_volume, counterparty_wallets):
    """Assign a risk score based on transaction behavior."""
    score = 0
    if transaction_count > 50: score += 20  # High frequency
    if total_volume > 10000: score += 30  # Large volume in SOL
    if any(wallet in HIGH_RISK_WALLETS for wallet in counterparty_wallets): score += 50  # Known risky wallets

    return "High Risk" if score >= 50 else "Medium Risk" if score >= 30 else "Low Risk"

def generate_network_graph(wallet_address, transaction_flows):
    """Generate an interactive transaction network graph."""
    G = nx.Graph()
    G.add_node(wallet_address, size=100, color="blue")

    node_sizes, node_colors, node_labels, edges = [], [], [], []
    for receiver, count in transaction_flows.items():
        size = count * 10 + 50
        color = "green" if count == 1 else "yellow" if count <= 5 else "red"

        G.add_node(receiver, size=size, color=color)
        G.add_edge(wallet_address, receiver)

        node_sizes.append(size)
        node_colors.append(color)
        node_labels.append(f"{receiver[:6]}...{receiver[-4:]} ({count})")

    pos = nx.spring_layout(G, seed=42)
    edge_x, edge_y = [], []
    for edge in G.edges():
        x0, y0 = pos[edge[0]]
        x1, y1 = pos[edge[1]]
        edge_x.extend([x0, x1, None])
        edge_y.extend([y0, y1, None])

    edge_trace = go.Scatter(x=edge_x, y=edge_y, line=dict(width=1, color='black'), hoverinfo='none', mode='lines')
    node_x, node_y, node_text, node_color, node_size = [], [], [], [], []
    for node in G.nodes():
        x, y = pos[node]
        node_x.append(x)
        node_y.append(y)
        node_text.append(node if node == wallet_address else node_labels.pop(0))
        node_color.append(G.nodes[node]["color"])
        node_size.append(G.nodes[node]["size"])

    node_trace = go.Scatter(x=node_x, y=node_y, mode='markers', hoverinfo='text',
                            marker=dict(size=node_size, color=node_color, line=dict(width=2, color='black')),
                            text=node_text)

    return go.Figure(data=[edge_trace, node_trace]).to_json()

@app.route("/")
def index():
    return render_template_string(HTML_TEMPLATE)

@app.route("/trace", methods=["POST"])
def trace_wallet():
    data = request.json
    wallet_address = data.get("wallet")
    transactions = get_wallet_transactions(wallet_address, limit=10)
    if not transactions: return jsonify({"error": "No transactions found"}), 404
    transaction_flows, total_volume = extract_transaction_flows(wallet_address, transactions)
    risk_score = assign_risk_score(len(transaction_flows), total_volume, transaction_flows.keys())
    graph_json = generate_network_graph(wallet_address, transaction_flows)
    return jsonify({"graph": graph_json, "risk_score": risk_score})

if __name__ == "__main__":
    app.run(debug=True)
