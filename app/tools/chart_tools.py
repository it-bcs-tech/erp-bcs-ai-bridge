import json
import base64
import io
import asyncio
import matplotlib.pyplot as plt
import matplotlib

# Set backend non-interactive (penting untuk server)
matplotlib.use('Agg')

CHART_TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "generate_chart_image",
        "description": (
            "Gunakan fungsi ini MUTLAK jika Anda diminta untuk membuat, menggambar, atau menampilkan grafik (chart). "
            "Kirimkan JSON berstruktur berisi title, chart_type, labels, dan datasets."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "chart_type": {
                    "type": "string",
                    "enum": ["bar", "pie", "line"],
                    "description": "Jenis grafik"
                },
                "title": {
                    "type": "string",
                    "description": "Judul grafik"
                },
                "labels": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Label pada sumbu X atau potongan pie"
                },
                "datasets": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "label": {"type": "string", "description": "Nama dataset"},
                            "data": {"type": "array", "items": {"type": "number"}, "description": "Nilai numerik data"}
                        },
                        "required": ["label", "data"]
                    },
                    "description": "Daftar data yang akan digambar"
                }
            },
            "required": ["chart_type", "title", "labels", "datasets"],
        },
    },
}

def _draw_matplotlib(chart_type: str, title: str, labels: list, datasets: list) -> str:
    plt.clf()
    fig, ax = plt.subplots(figsize=(8, 5))
    
    if chart_type == "bar":
        x = range(len(labels))
        width = 0.8 / len(datasets)
        for i, ds in enumerate(datasets):
            pos = [px + i*width - 0.4 + width/2 for px in x]
            ax.bar(pos, ds.get("data", []), width, label=ds.get("label", ""))
        ax.set_xticks(x)
        ax.set_xticklabels(labels, rotation=15, ha="right")
        if len(datasets) > 1 or datasets[0].get("label"):
            ax.legend()
            
    elif chart_type == "line":
        for ds in datasets:
            ax.plot(labels, ds.get("data", []), marker="o", label=ds.get("label", ""))
        ax.set_xticks(range(len(labels)))
        ax.set_xticklabels(labels, rotation=15, ha="right")
        if len(datasets) > 1 or datasets[0].get("label"):
            ax.legend()
            
    elif chart_type == "pie":
        data = datasets[0].get("data", [])
        ax.pie(data, labels=labels, autopct='%1.1f%%', startangle=90)
        ax.axis('equal')
        
    plt.title(title)
    plt.tight_layout()
    
    import uuid
    import os
    
    # Buat nama file unik dan path penyimpanannya
    filename = f"chart_{uuid.uuid4().hex}.png"
    save_dir = os.path.join(os.getcwd(), "app", "static", "charts")
    os.makedirs(save_dir, exist_ok=True)
    filepath = os.path.join(save_dir, filename)
    
    # Simpan sebagai file
    plt.savefig(filepath, format="png", bbox_inches='tight')
    plt.close(fig)
    
    # Hasilkan link publik statis untuk dirender oleh LLM via SvelteKit
    image_url = f"http://localhost:8000/static/charts/{filename}"
    
    return f"\n\n![{title}]({image_url})\n\n*(Grafik dirender secara lokal oleh Matplotlib)*"

async def generate_chart_image(**kwargs) -> str:
    """
    Menerima argumen kwargs dari AI (chart_type, title, labels, datasets),
    kemudian merendernya dengan matplotlib secara asynchronous.
    """
    try:
        # Jika AI secara keliru masih menggunakan skema lama (chart_config string)
        if "chart_config" in kwargs:
            return "Gagal merender: Anda masih mengirimkan 'chart_config'. Silakan ikuti struktur parameter yang baru: chart_type, title, labels, dan datasets."

        chart_type = kwargs.get("chart_type", "bar")
        title = kwargs.get("title", "Visualisasi Data")
        labels = kwargs.get("labels", [])
        datasets = kwargs.get("datasets", [])
        
        # Penanganan Typo AI (Groq sering membuat kesalahan format datasets)
        if "dataset" in kwargs and not datasets:
            val = kwargs["dataset"]
            if isinstance(val, list):
                if val and isinstance(val[0], dict):
                    datasets = val
                else:
                    datasets = [{"label": "Data", "data": val}]
            elif isinstance(val, dict):
                datasets = [val]
                
        # Typo dari Groq: x_labels dan y_values
        if "x_labels" in kwargs and not labels:
            labels = kwargs["x_labels"]
        if "y_values" in kwargs and not datasets:
            val = kwargs["y_values"]
            if isinstance(val, list):
                datasets = [{"label": "Data", "data": val}]
                
        # Jika AI mengirim 'datasets' tapi isinya hanya angka langsung (list of int/float)
        if datasets and not isinstance(datasets[0], dict):
            datasets = [{"label": "Data", "data": datasets}]
            
        markdown_result = await asyncio.to_thread(_draw_matplotlib, chart_type, title, labels, datasets)
        return markdown_result
    except Exception as e:
        return f"Gagal merender grafik Matplotlib: {str(e)}"
