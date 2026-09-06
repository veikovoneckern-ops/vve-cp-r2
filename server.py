def status_lesen():
    try:
        response = requests.get("http://localhost:8000/status")
        if response.status_code == 200:
            data = response.json()
            return {
                "dienste": data.get("services", []),
                "strom_server": data.get("power", {}).get("server", "nicht verfügbar"),
                "strom_dock": data.get("power", {}).get("dock", "nicht verfügbar"),
                "temperatur": data.get("temps_c", []),
                "modell": data.get("ollama_models", []),
                "jobs": data.get("ollama_running", []),
                "gpu_nvidia": data.get("gpu_nvidia", [])
            }
        else:
            return {
                "dienste": [],
                "strom_server": "nicht verfügbar",
                "strom_dock": "nicht verfügbar",
                "temperatur": [],
                "modell": [],
                "jobs": [],
                "gpu_nvidia": []
            }
    except Exception as e:
        print(f"Fehler beim Abrufen des Status: {e}")
        return {
            "dienste": [],
            "strom_server": "nicht verfügbar",
            "strom_dock": "nicht verfügbar",
            "temperatur": [],
            "modell": [],
            "jobs": [],
            "gpu_nvidia": []
        }