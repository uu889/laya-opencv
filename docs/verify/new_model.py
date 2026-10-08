"""Step 1: build a blank Laya-format checkpoint from an arbitrary HF encoder.

Offline stand-in for `intfloat/multilingual-e5-small`: the same model class
(XLMRobertaModel), randomly initialised and much smaller, with a tokenizer trained
on the sample text. With network access the `make_encoder()` body is replaced by
the plain HF id and this script is otherwise unchanged.
"""
import json
import os
import sys

import torch
from tokenizers import Tokenizer, models, pre_tokenizers, trainers, normalizers
from transformers import PreTrainedTokenizerFast, XLMRobertaConfig, XLMRobertaModel

from laya.common import build_model
from laya.train import save_checkpoint

data_path, encoder_dir, out_dir = sys.argv[1:4]


def make_encoder(path: str) -> str:
    texts = [json.loads(l)["state"] for l in open(data_path, encoding="utf-8")]
    texts += ["yes no true false few many acceptable 合格 不合格 缺陷 数量 等级"]
    tok = Tokenizer(models.Unigram())
    tok.normalizer = normalizers.NFKC()
    tok.pre_tokenizer = pre_tokenizers.Metaspace()
    specials = ["<s>", "<pad>", "</s>", "<unk>", "<mask>"]
    tok.train_from_iterator(texts, trainers.UnigramTrainer(vocab_size=600, special_tokens=specials, unk_token="<unk>"))
    fast = PreTrainedTokenizerFast(tokenizer_object=tok, bos_token="<s>", eos_token="</s>", pad_token="<pad>",
                                   unk_token="<unk>", mask_token="<mask>", cls_token="<s>", sep_token="</s>",
                                   model_max_length=512)
    # XLM-R-style: <s> ... </s> around the sequence
    from tokenizers.processors import TemplateProcessing
    fast.backend_tokenizer.post_processor = TemplateProcessing(
        single="<s> $A </s>", pair="<s> $A </s> </s> $B </s>",
        special_tokens=[("<s>", fast.convert_tokens_to_ids("<s>")), ("</s>", fast.convert_tokens_to_ids("</s>"))])
    cfg = XLMRobertaConfig(vocab_size=len(fast), hidden_size=128, num_hidden_layers=4, num_attention_heads=4,
                           intermediate_size=256, max_position_embeddings=514, pad_token_id=fast.pad_token_id,
                           bos_token_id=fast.bos_token_id, eos_token_id=fast.eos_token_id)
    torch.manual_seed(0)
    XLMRobertaModel(cfg).save_pretrained(path)
    fast.save_pretrained(path)
    return path


encoder = make_encoder(encoder_dir)

cfg = {
    "encoder": encoder,          # any HF encoder id or local dir
    "head_layers": 2,
    "max_len": 512,
    "head_max_len": 192,
    "option_layout": "sequential",
}
model = build_model(cfg)          # AutoModel.from_pretrained(encoder) + fresh decision head
from transformers import AutoTokenizer
tok = AutoTokenizer.from_pretrained(encoder)
n_enc = sum(p.numel() for p in model.encoder.parameters())
n_all = sum(p.numel() for p in model.parameters())
print(f"encoder {type(model.encoder).__name__}: {n_enc/1e6:.2f}M params, total {n_all/1e6:.2f}M")
save_checkpoint(model, tok, cfg, out_dir)
print("saved blank checkpoint ->", out_dir, sorted(os.listdir(out_dir)))
