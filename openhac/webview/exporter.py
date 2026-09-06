"""Interactive Web-Based Graph Explorer Generator.

This module replaces the legacy static KiCad schematic generator. It exports the 
Intermediate Representation (IR) into a standalone, highly aesthetic HTML/JS 
single-page application using Cytoscape.js for interactive topology exploration.
"""

import json
from pathlib import Path

from openhac.core.board import Board


def generate_interactive_webview(board: Board, output_path: str | Path) -> None:
    """Generate a standalone HTML file containing the interactive hardware graph.
    
    Args:
        board: The compiled Board object.
        output_path: Path to write the HTML file.
    """
    # 1. Get the IR data
    from openhac.compiler.ir_export import export_hardware_ir
    ir_json_str = export_hardware_ir(board)
    ir_data = json.loads(ir_json_str)
    
    # 2. Transform IR into Cytoscape.js Elements
    cy_elements = []
    
    # Nodes (Components)
    for comp in ir_data.get("components", []):
        ref = comp.get("refdes", "?")
        val = comp.get("value", "")
        # Try to guess category from refdes
        cat = "IC"
        if ref.startswith("R"): cat = "Resistor"
        elif ref.startswith("C"): cat = "Capacitor"
        elif ref.startswith("L"): cat = "Inductor"
        elif ref.startswith("D"): cat = "Diode"
        elif ref.startswith("Q"): cat = "Transistor"
        elif ref.startswith("J") or ref.startswith("P"): cat = "Connector"
        
        cy_elements.append({
            "group": "nodes",
            "data": {
                "id": ref,
                "label": f"{ref}\n{val}",
                "category": cat,
                "full_data": comp
            }
        })
        
    # Edges (Nets)
    # A net connects multiple pins. For graph simplicity, we'll create a "Net" node
    # and connect the components to it, OR we can connect components directly if it's point-to-point.
    # To keep it beautiful, let's create virtual "Net" nodes for buses, and direct edges for 2-pin nets.
    net_idx = 0
    for net in ir_data.get("nets", []):
        net_name = net.get("name", "NC")
        if net_name == "NC" or not net.get("pins"):
            continue
            
        # Extract unique component refs attached to this net
        attached_refs = list(set([pin_ref.split(".")[0] for pin_ref in net["pins"]]))
        
        if len(attached_refs) == 2:
            # Direct connection
            cy_elements.append({
                "group": "edges",
                "data": {
                    "id": f"e_{net_idx}",
                    "source": attached_refs[0],
                    "target": attached_refs[1],
                    "label": net_name
                }
            })
            net_idx += 1
        elif len(attached_refs) > 2:
            # Bus connection: create a virtual hub node
            hub_id = f"net_hub_{net_name}"
            cy_elements.append({
                "group": "nodes",
                "data": {
                    "id": hub_id,
                    "label": net_name,
                    "category": "NetHub"
                }
            })
            for ref in attached_refs:
                cy_elements.append({
                    "group": "edges",
                    "data": {
                        "id": f"e_{net_idx}",
                        "source": hub_id,
                        "target": ref,
                        "label": net_name
                    }
                })
                net_idx += 1

    cy_elements_json = json.dumps(cy_elements).replace("<", "\\u003c")

    # 3. Generate HTML Template with Rich Aesthetics
    html_content = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>OpenHaC Hardware Graph Explorer: __PROJECT_NAME__</title>
    <!-- CODE-005: no Google Fonts. Cytoscape CDN remains until FAB-041 delete. -->
    <!-- Cytoscape.js -->
    <script src="https://cdnjs.cloudflare.com/ajax/libs/cytoscape/3.28.1/cytoscape.min.js"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/dagre/0.8.5/dagre.min.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/cytoscape-dagre@2.5.0/cytoscape-dagre.min.js"></script>
    
    <style>
        :root {
            --bg-color: #0B0E14;
            --surface-color: rgba(20, 25, 35, 0.6);
            --surface-border: rgba(255, 255, 255, 0.08);
            --text-primary: #FFFFFF;
            --text-secondary: #94A3B8;
            --accent-glow: #3B82F6;
            --accent-ic: #8B5CF6;
            --accent-passive: #10B981;
            --accent-connector: #F59E0B;
            --accent-net: #EC4899;
        }

        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }

        body {
            font-family: system-ui, sans-serif;
            background-color: var(--bg-color);
            background-image: 
                radial-gradient(circle at 15% 50%, rgba(59, 130, 246, 0.15), transparent 25%),
                radial-gradient(circle at 85% 30%, rgba(139, 92, 246, 0.15), transparent 25%);
            color: var(--text-primary);
            height: 100vh;
            width: 100vw;
            overflow: hidden;
            display: flex;
            flex-direction: column;
        }

        header {
            padding: 20px 40px;
            background: var(--surface-color);
            backdrop-filter: blur(12px);
            -webkit-backdrop-filter: blur(12px);
            border-bottom: 1px solid var(--surface-border);
            display: flex;
            justify-content: space-between;
            align-items: center;
            z-index: 100;
        }

        .brand h1 {
            font-weight: 800;
            font-size: 1.5rem;
            letter-spacing: -0.5px;
            background: linear-gradient(135deg, #FFFFFF 0%, #94A3B8 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }
        
        .brand span {
            color: var(--accent-glow);
            -webkit-text-fill-color: var(--accent-glow);
        }

        .stats {
            display: flex;
            gap: 20px;
            font-size: 0.9rem;
            font-weight: 600;
            color: var(--text-secondary);
        }
        
        .stats div span {
            color: var(--text-primary);
            font-family: 'JetBrains Mono', monospace;
            background: rgba(255,255,255,0.05);
            padding: 4px 8px;
            border-radius: 6px;
            margin-left: 6px;
        }

        #main-container {
            display: flex;
            flex: 1;
            position: relative;
        }

        #cy {
            flex: 1;
            height: 100%;
            z-index: 1;
        }

        /* Glassmorphism Inspector Panel */
        #inspector {
            width: 380px;
            background: var(--surface-color);
            backdrop-filter: blur(16px);
            -webkit-backdrop-filter: blur(16px);
            border-left: 1px solid var(--surface-border);
            padding: 30px;
            display: flex;
            flex-direction: column;
            gap: 20px;
            z-index: 10;
            transition: transform 0.3s cubic-bezier(0.4, 0, 0.2, 1);
            overflow-y: auto;
        }

        .inspector-title {
            font-size: 1.2rem;
            font-weight: 600;
            padding-bottom: 15px;
            border-bottom: 1px solid var(--surface-border);
            color: var(--text-primary);
        }

        .prop-group {
            background: rgba(0,0,0,0.2);
            border-radius: 12px;
            padding: 15px;
            border: 1px solid var(--surface-border);
        }

        .prop-row {
            display: flex;
            justify-content: space-between;
            margin-bottom: 10px;
            font-size: 0.9rem;
        }

        .prop-row:last-child {
            margin-bottom: 0;
        }

        .prop-label {
            color: var(--text-secondary);
        }

        .prop-val {
            font-family: 'JetBrains Mono', monospace;
            color: var(--accent-glow);
            text-align: right;
            max-width: 60%;
            word-wrap: break-word;
        }

        .pin-list {
            margin-top: 10px;
            display: flex;
            flex-direction: column;
            gap: 6px;
        }

        .pin-item {
            display: flex;
            justify-content: space-between;
            background: rgba(255,255,255,0.03);
            padding: 8px 12px;
            border-radius: 6px;
            font-size: 0.85rem;
            border-left: 3px solid var(--accent-glow);
        }
        
        .empty-state {
            color: var(--text-secondary);
            text-align: center;
            margin-top: 50px;
            font-style: italic;
        }
    </style>
</head>
<body>

    <header>
        <div class="brand">
            <h1>OpenHaC <span>Graph Explorer</span></h1>
        </div>
        <div class="stats">
            <div>Components: <span>__STATS_COMPONENTS__</span></div>
            <div>Nets: <span>__STATS_NETS__</span></div>
            <div>Constraints: <span>__STATS_CONSTRAINTS__</span></div>
        </div>
    </header>

    <div id="main-container">
        <div id="cy"></div>
        
        <div id="inspector">
            <div class="inspector-title">Properties Inspector</div>
            <div id="inspector-content">
                <div class="empty-state">Select a node or edge to view its details.</div>
            </div>
        </div>
    </div>

    <script>
        // Initialize Cytoscape with Dagre layout
        const elements = __CY_ELEMENTS_JSON__;
        
        const cy = cytoscape({
            container: document.getElementById('cy'),
            elements: elements,
            style: [
                {
                    selector: 'node',
                    style: {
                        'background-color': '#1E293B',
                        'label': 'data(label)',
                        'color': '#FFFFFF',
                        'text-wrap': 'wrap',
                        'text-halign': 'center',
                        'text-valign': 'center',
                        'font-family': 'Outfit',
                        'font-size': '10px',
                        'font-weight': '600',
                        'width': '60px',
                        'height': '60px',
                        'border-width': 2,
                        'border-color': '#334155',
                        'transition-property': 'background-color, border-color, width, height',
                        'transition-duration': '0.2s'
                    }
                },
                {
                    selector: 'node[category="IC"]',
                    style: { 'border-color': 'var(--accent-ic)', 'shape': 'round-rectangle' }
                },
                {
                    selector: 'node[category="Resistor"], node[category="Capacitor"], node[category="Inductor"]',
                    style: { 'border-color': 'var(--accent-passive)', 'width': '40px', 'height': '40px' }
                },
                {
                    selector: 'node[category="Connector"]',
                    style: { 'border-color': 'var(--accent-connector)' }
                },
                {
                    selector: 'node[category="NetHub"]',
                    style: { 
                        'background-color': 'var(--accent-net)', 
                        'border-width': 0,
                        'width': '15px', 
                        'height': '15px',
                        'label': 'data(id)',
                        'text-valign': 'bottom',
                        'text-margin-y': 5,
                        'color': 'var(--text-secondary)'
                    }
                },
                {
                    selector: 'edge',
                    style: {
                        'width': 2,
                        'line-color': '#334155',
                        'curve-style': 'bezier',
                        'label': 'data(label)',
                        'font-size': '8px',
                        'color': '#64748B',
                        'text-rotation': 'autorotate',
                        'text-background-opacity': 1,
                        'text-background-color': 'var(--bg-color)',
                        'text-background-padding': '2px',
                        'transition-property': 'line-color, width',
                        'transition-duration': '0.2s'
                    }
                },
                {
                    selector: 'node:selected',
                    style: {
                        'border-width': 4,
                        'border-color': '#FFFFFF',
                        'background-color': 'var(--accent-glow)'
                    }
                },
                {
                    selector: 'edge:selected',
                    style: {
                        'width': 4,
                        'line-color': 'var(--accent-glow)'
                    }
                }
            ],
            layout: {
                name: 'dagre',
                nodeSep: 60,
                rankSep: 100,
                animate: true,
                animationDuration: 800
            }
        });

        // Interaction Logic
        const inspectorContent = document.getElementById('inspector-content');
        function esc(s) {
            return String(s == null ? '' : s)
                .replace(/&/g, '&amp;').replace(/</g, '&lt;')
                .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
        }

        cy.on('tap', 'node', function(evt){
            const node = evt.target;
            const data = node.data();
            
            if(data.category === 'NetHub') {
                inspectorContent.innerHTML = `<div class="empty-state">Bus/Net Hub:<br><br><span style="color:var(--accent-net)">${esc(data.label)}</span></div>`;
                return;
            }
            
            const fullData = data.full_data || {};
            const fields = fullData.fields || {};
            const pins = fullData.pins || [];

            let html = `
                <div class="prop-group">
                    <div class="prop-row"><span class="prop-label">RefDes</span><span class="prop-val">${esc(fullData.refdes || '?')}</span></div>
                    <div class="prop-row"><span class="prop-label">Value</span><span class="prop-val">${esc(fullData.value || 'N/A')}</span></div>
                    <div class="prop-row"><span class="prop-label">Footprint</span><span class="prop-val" style="font-size: 0.75rem;">${esc(fullData.footprint || 'Unassigned')}</span></div>
                </div>
            `;
            
            if(Object.keys(fields).length > 0) {
                html += `<div class="prop-group" style="margin-top: 15px;">`;
                for(const [k, v] of Object.entries(fields)) {
                    html += `<div class="prop-row"><span class="prop-label">${esc(k)}</span><span class="prop-val" style="font-size: 0.75rem;">${esc(v)}</span></div>`;
                }
                html += `</div>`;
            }

            if(pins.length > 0) {
                html += `<div style="margin-top: 20px;">
                            <div class="prop-label" style="margin-bottom: 10px;">Pins & Nets</div>
                            <div class="pin-list">`;
                pins.forEach(p => {
                    let logic = p.logic_level ? ` (${esc(p.logic_level)}V)` : '';
                    html += `<div class="pin-item">
                                <span><strong>${esc(p.number)}</strong> - ${esc(p.name)}</span>
                                <span style="color:var(--accent-glow)">${esc(p.net)}${logic}</span>
                             </div>`;
                });
                html += `   </div>
                         </div>`;
            }

            inspectorContent.innerHTML = html;
        });

        cy.on('tap', 'edge', function(evt){
            const edge = evt.target;
            const data = edge.data();
            inspectorContent.innerHTML = `
                <div class="prop-group">
                    <div class="prop-row"><span class="prop-label">Net Name</span><span class="prop-val">${esc(data.label)}</span></div>
                    <div class="prop-row"><span class="prop-label">Source</span><span class="prop-val">${esc(data.source)}</span></div>
                    <div class="prop-row"><span class="prop-label">Target</span><span class="prop-val">${esc(data.target)}</span></div>
                </div>
            `;
        });

        cy.on('tap', function(evt){
            if(evt.target === cy) {
                inspectorContent.innerHTML = '<div class="empty-state">Select a node or edge to view its details.</div>';
            }
        });
        
    </script>
</body>
</html>"""

    # Replace template variables
    html_content = html_content.replace("__PROJECT_NAME__", str(ir_data.get('project', {}).get('name', 'Board')))
    html_content = html_content.replace("__STATS_COMPONENTS__", str(len(ir_data.get('components', []))))
    html_content = html_content.replace("__STATS_NETS__", str(len(ir_data.get('nets', []))))
    html_content = html_content.replace("__STATS_CONSTRAINTS__", str(len(ir_data.get('project', {}).get('constraints', {}))))
    html_content = html_content.replace("__CY_ELEMENTS_JSON__", cy_elements_json)

    out_path = Path(output_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html_content, encoding="utf-8")
