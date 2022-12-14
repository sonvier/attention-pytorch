import math
import torch
import torch.nn as nn
import torch.nn.functional as F


class ScaledDotProductAttention(nn.Module):
    def __init__(self, dropout=0):
        super().__init__()
        self.dropout = nn.Dropout(dropout)

    def forward(self, query, key, value, attn_mask=None):
        """
        Args:
            query: (N, n, d_k)
            key: (N, m, d_k)
            value: (N, m, d_v)
            attn_mask: (N, n, m)
        """
        assert query.size(2) == key.size(2)
        scores = query @ key.transpose(1, 2) / math.sqrt(query.size(2))
        if attn_mask is not None:
            scores = scores.masked_fill(attn_mask, float('-inf'))
        attn_weights = F.softmax(scores, dim=-1)
        return self.dropout(attn_weights) @ value


class AdditiveAttention(nn.Module):
    def __init__(self, query_size, key_size, hidden_size, drouput=0):
        super().__init__()
        self.W_q = nn.Linear(query_size, hidden_size, bias=False)
        self.W_k = nn.Linear(key_size, hidden_size, bias=False)
        self.W_v = nn.Linear(hidden_size, 1, bias=False)
        self.dropout = nn.Dropout(drouput)

    def forward(self, query, key, value, attn_mask=None):
        """
        Args:
            query: (N, n, d_q)
            key: (N, m, d_k)
            value: (N, m, d_v)
            attn_mask: (N, n, m)
        """
        query, key = self.W_q(query).unsqueeze(2), self.W_k(key).unsqueeze(1)
        scores = self.W_v(torch.tanh(query + key)).squeeze()
        if attn_mask is not None:
            scores = scores.masked_fill(attn_mask, float('-inf'))
        attn_weights = F.softmax(scores, dim=-1)
        return self.dropout(attn_weights) @ value
