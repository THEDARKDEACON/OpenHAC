import json
import urllib.request
import os

def inspect_jlc_sku(sku):
    url = "https://jlcpcb.com/api/overseas-pcb-order/v1/shoppingCart/smtGood/selectSmtComponentList/v2"
    body = json.dumps({
        "currentPage": 1,
        "pageSize": 20,
        "keyword": sku,
        "searchType": 2,
    }).encode("utf-8")
    
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        },
    )
    
    with urllib.request.urlopen(req, timeout=45) as resp:
        data = json.loads(resp.read().decode())
        
    rows = (data.get("data") or {}).get("componentPageInfo") or {}
    lst = rows.get("list") or []
    for row in lst:
        if str(row.get("componentCode")).strip().upper() == sku.upper():
            print(json.dumps(row, indent=2))
            return row
    print("Part not found in response")
    return None

if __name__ == "__main__":
    inspect_jlc_sku("C6396158")
