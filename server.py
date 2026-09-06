async def status_lesen() -> dict[str, Any]:
    lage = {"quelle": None, "dienste": "nicht verfuegbar", "strom_server": "nicht verfuegbar",
            "strom_dock": "nicht verfuegbar", "temperatur": "nicht verfuegbar",
            "modell": "nicht verfuegbar", "jobs": "nicht verfuegbar"}
    if not STATUS_URL:
        return lage
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            antwort = await client.get(f"{STATUS_URL}/status")
        if antwort.status_code >= 400:
            return lage
        lage["quelle"] = STATUS_URL
        roh = antwort.json()
        if isinstance(roh, dict):
            for schluessel in ("services", "power", "temps_c", "ollama_models", "ollama_running", "gpu_nvidia"):
                if schluessel in roh and roh[schluessel] not in (None, ""):
                    lage[schluessel] = roh[schluessel]
    except httpx.HTTPError:
        return lage
    return lage