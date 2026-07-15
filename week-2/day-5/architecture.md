# Architecture — Preference-Aware Travel RAG Assistant

## System diagram

```mermaid
flowchart TD
    subgraph OFFLINE["🛠️ OFFLINE · ingest.py (run once)"]
        direction TB
        W["Wikivoyage API<br/>5 city pages"] --> CL["Clean plain text<br/>== section headers =="]
        CL --> CH["Chunk ~160 words<br/>See / Do / Eat / Drink"]
        CH --> MD["Derive metadata<br/>url · city · category · price_level"]
        MD --> EMB1["bge-small embeddings"]
        EMB1 --> QD[("Qdrant collection<br/>vector + payload<br/>embedded, on-disk")]
    end

    subgraph ONLINE["🚀 ONLINE · app.py (Streamlit)"]
        direction TB
        UQ["👤 User query<br/>'3-day Berlin trip with cheap food and art'"] --> PREF["① preferences.py — Groq → JSON<br/>city · categories · price_levels · days<br/>(validated vs controlled vocab)"]
        PREF --> RET["② retriever.py<br/>Qdrant search + NATIVE metadata filter"]
        RET --> RR["cross-encoder rerank<br/>ms-marco (precision)"]
        RR --> JUDGE{"③ context judge<br/>Groq: good enough?"}
        RR -.- RRNOTE["price = soft rerank boost<br/>(not a hard filter — noisy field)"]
        JUDGE -- context_good --> GEN["④ generator.py — Groq<br/>grounded answer with citations"]
        JUDGE -- context_insufficient --> RELAX["relax filters<br/>drop category → then city"]
        RELAX -. retry once .-> RET
        GEN --> OUT["🖥️ UI output<br/>answer + debug panel:<br/>preferences · trace · chunks · URLs"]
    end

    QD -. loaded once .-> RET

    classDef groq fill:#f4a,stroke:#a05,color:#fff;
    classDef local fill:#4ad,stroke:#058,color:#fff;
    classDef store fill:#fb4,stroke:#a70,color:#000;
    class PREF,JUDGE,GEN groq;
    class RR,EMB1 local;
    class QD store;
```

<details>
<summary>🖼️ PNG fallback (if your viewer doesn't render Mermaid)</summary>

![System diagram](architecture_system.png)

</details>

**Legend:** 🟣 Groq LLM calls (`gpt-oss-120b`) · 🔵 local models (bge-small, cross-encoder) · 🟠 vector store (Qdrant).

## The 4 stages the UI must show

| Stage         | Module                      | Input → Output                               | LLM?                   |
| ------------- | --------------------------- | -------------------------------------------- | ---------------------- |
| **query**     | `app.py`                    | user text                                    | —                      |
| **retrieval** | `store.py` + `retriever.py` | query → filtered, reranked chunks            | rerank = cross-encoder |
| **reasoning** | `retriever.py`              | chunks → good/insufficient + relax decisions | judge = Groq           |
| **answer**    | `generator.py`              | query + chunks → grounded answer             | Groq                   |

## Two-stage retrieval (why recall then precision)

```mermaid
flowchart LR
    Q["query"] --> F["Qdrant<br/>bi-encoder search<br/>+ native filter"]
    F --> C["~30 candidates<br/>(high recall)"]
    C --> X["cross-encoder<br/>joint query↔chunk scoring"]
    X --> T["top 5<br/>(high precision)"]
    T --> A["answer generation"]
```

<details>
<summary>🖼️ PNG fallback (if your viewer doesn't render Mermaid)</summary>

![Two-stage retrieval](architecture_retrieval.png)

</details>

- **Recall stage** (Qdrant bi-encoder + native filter): fast; casts a wide net inside the metadata filter. Query and chunk are embedded _separately_.
- **Precision stage** (cross-encoder): slower but accurate; re-scores the ~30 candidates _jointly_ and keeps the best 5. No single model does both well at scale — hence the split.

## Request sequence

```mermaid
sequenceDiagram
    actor U as User
    participant UI as app.py
    participant P as preferences.py
    participant R as retriever.py
    participant Q as Qdrant
    participant CE as cross-encoder
    participant Gq as Groq

    U->>UI: travel question
    UI->>P: extract(query)
    P->>Gq: query understanding (JSON mode)
    Gq-->>P: {city, categories, price_levels, days}
    P-->>UI: validated preferences
    UI->>R: retrieve(query, prefs)
    loop until context_good OR filters exhausted
        R->>Q: search + metadata filter
        Q-->>R: candidate chunks
        R->>CE: rerank(query, chunks)
        CE-->>R: top-5
        R->>Gq: judge context
        Gq-->>R: good / insufficient (+reason)
    end
    R-->>UI: chunks + trace
    UI->>Gq: generate grounded answer
    Gq-->>UI: answer + [n] citations
    UI-->>U: answer + debug panel
```

<details>
<summary>🖼️ PNG fallback (if your viewer doesn't render Mermaid)</summary>

![Request sequence](architecture_sequence.png)

</details>

