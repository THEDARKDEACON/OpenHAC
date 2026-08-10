import os

def create_dummy_footprint(pin_count):
    # Create ~/.kiro/openhac/Package_SMD.pretty
    out_dir = os.path.expanduser("~/.kiro/openhac/Package_SMD.pretty")
    os.makedirs(out_dir, exist_ok=True)
    
    fp_path = os.path.join(out_dir, f"Generic_{pin_count}PIN.kicad_mod")
    with open(fp_path, "w") as f:
        f.write(f"(footprint \"Package_SMD:Generic_{pin_count}PIN\"\n")
        f.write("  (layer \"F.Cu\")\n")
        f.write("  (attr smd)\n")
        f.write("  (fp_text reference \"REF**\" (at 0 -2.5) (layer \"F.SilkS\")\n")
        f.write("    (effects (font (size 1 1) (thickness 0.15)))\n")
        f.write("  )\n")
        f.write("  (fp_text value \"Generic\" (at 0 2.5) (layer \"F.Fab\")\n")
        f.write("    (effects (font (size 1 1) (thickness 0.15)))\n")
        f.write("  )\n")
        
        # Draw a simple box
        w = max(5.0, pin_count * 0.5)
        h = max(5.0, pin_count * 0.5)
        f.write(f"  (fp_line (start -{w/2} -{h/2}) (end {w/2} -{h/2}) (layer \"F.SilkS\") (width 0.12))\n")
        f.write(f"  (fp_line (start {w/2} -{h/2}) (end {w/2} {h/2}) (layer \"F.SilkS\") (width 0.12))\n")
        f.write(f"  (fp_line (start {w/2} {h/2}) (end -{w/2} {h/2}) (layer \"F.SilkS\") (width 0.12))\n")
        f.write(f"  (fp_line (start -{w/2} {h/2}) (end -{w/2} -{h/2}) (layer \"F.SilkS\") (width 0.12))\n")
        
        # Place pads
        cols = int(pin_count**0.5)
        if cols == 0: cols = 1
        pitch = 1.27
        start_x = -(cols-1)*pitch/2
        start_y = -(cols-1)*pitch/2
        
        for i in range(1, pin_count + 1):
            col = (i-1) % cols
            row = (i-1) // cols
            px = start_x + col * pitch
            py = start_y + row * pitch
            f.write(f"  (pad \"{i}\" smd rect (at {px} {py}) (size 0.8 0.8) (layers \"F.Cu\" \"F.Paste\" \"F.Mask\"))\n")
            
        f.write(")\n")
        print(f"Generated {fp_path}")

if __name__ == "__main__":
    for p in [2, 4, 5, 6, 12, 16, 24, 64, 99, 100, 256]:
        create_dummy_footprint(p)
