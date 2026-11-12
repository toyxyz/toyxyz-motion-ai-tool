"""Pinned, pre-merged encoders. Neither profile applies extra PEFT adapters."""
PROFILES = {
    'bf16': {
        'repo': 'McGill-NLP/LLM2Vec-Meta-Llama-3-8B-Instruct-mntp',
        'revision': '31474e395ada192e8ed1586db6be79fb3b70c9c0',
        'adapter_repo': 'McGill-NLP/LLM2Vec-Meta-Llama-3-8B-Instruct-mntp-supervised',
        'adapter_revision': 'baa8ebf04a1c2500e61288e7dad65e8ae42601a7',
        'port': 8765,
    },
    'int8': {
        'repo': 'voxta/Llama-3-8B-LLM2Vec-ARDY-INT8',
        'revision': '96c7eb1cc9100cd3925662d1093926c00b64a698',
        'port': 8766,
    },
    'nf4': {
        'repo': 'voxta/Llama-3-8B-LLM2Vec-ARDY-NF4',
        'revision': 'f746923e9e7edb3b6fc54aae7dfd8cecb0f52a8f',
        'port': 8767,
    },
}
