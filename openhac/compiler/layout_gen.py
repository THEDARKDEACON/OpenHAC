import sys
import subprocess
import os

def generate_layout(netlist_path: str, output_pcb_path: str, size_mm: tuple):
    print(f"Generating physical layout for {netlist_path} -> {output_pcb_path}")
    
    try:
        import pcbnew
        board = pcbnew.BOARD()
        
        edge_cuts = board.GetLayerID('Edge.Cuts')
        w, h = size_mm
        
        pts = [
            pcbnew.wxPoint(0, 0),
            pcbnew.wxPoint(int(pcbnew.FromMM(w)), 0),
            pcbnew.wxPoint(int(pcbnew.FromMM(w)), int(pcbnew.FromMM(h))),
            pcbnew.wxPoint(0, int(pcbnew.FromMM(h)))
        ]
        
        for i in range(4):
            seg = pcbnew.PCB_SHAPE(board)
            seg.SetShape(pcbnew.SHAPE_T_SEGMENT)
            seg.SetStart(pts[i])
            seg.SetEnd(pts[(i+1)%4])
            seg.SetLayer(edge_cuts)
            seg.SetWidth(int(pcbnew.FromMM(0.1)))
            board.Add(seg)
        
        pcbnew.SaveBoard(output_pcb_path, board)
        print("Board outline generated successfully.")
    except Exception as e:
        print(f"KiCad PCBNew API failed or unavailable: {e}")
        with open(output_pcb_path, 'w') as f:
            f.write(f"(kicad_pcb (version 20240108) (generator pcbnew)\n  (general)\n  (paper \"A4\")\n)\n")
