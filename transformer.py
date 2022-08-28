import math
import torch
import torch.nn as nn
import torch.nn.functional as F


class MultiHeadAttention(nn.Module):
    def __init__(self, embed_dim, num_heads, dropout=0.1, bias=True):
        super().__init__()
        self.embed_dim = embed_dim
        self.num_heads = num_heads
        self.head_dim = embed_dim // num_heads
        self.dropout = dropout
        assert self.head_dim * num_heads == embed_dim

        self.q_proj = nn.Linear(embed_dim, embed_dim, bias=bias)
        self.k_proj = nn.Linear(embed_dim, embed_dim, bias=bias)
        self.v_proj = nn.Linear(embed_dim, embed_dim, bias=bias)
        self.out_proj = nn.Linear(embed_dim, embed_dim, bias=bias)

    def forward(self, query, key, value, attn_mask=None, key_padding_mask=None):
        """
        Args:
            query: (n, N, embed_dim)
            key: (m, N, embed_dim)
            value: (m, N, embed_dim)
            attn_mask (bool Tensor or float Tensor): (n, m) or (N * num_heads, n, m)
            key_padding_mask (bool Tensor): (N, m)

        Returns:
            attn_output: (n, N, embed_dim)
            attn_output_weights: (N, num_heads, n, m)
        """
        return self._multi_head_forward_attention(query,
                                                  key,
                                                  value,
                                                  dropout_p=self.dropout,
                                                  attn_mask=attn_mask,
                                                  key_padding_mask=key_padding_mask,
                                                  training=self.training)

    def _multi_head_forward_attention(self, query, key, value, dropout_p, attn_mask=None, key_padding_mask=None, training=True):
        q, k, v = self.q_proj(query), self.k_proj(key), self.v_proj(value)
        n, N, embed_dim = q.size()
        m = key.size(0)

        if attn_mask is not None:
            if attn_mask.dim() == 2:
                assert attn_mask.shape == (n, m)
                attn_mask = attn_mask.unsqueeze(0)
            elif attn_mask.dim() == 3:
                assert attn_mask.shape == (N * self.num_heads, n, m)
            else:
                raise RuntimeError

        if key_padding_mask is not None:
            assert key_padding_mask.shape == (N, m)
            key_padding_mask = key_padding_mask.view(N, 1, 1, m).repeat(1, self.num_heads, 1, 1).reshape(N * self.num_heads, 1, m)
            if attn_mask is None:
                attn_mask = key_padding_mask
            elif attn_mask.dtype == torch.bool:
                attn_mask = attn_mask.logical_or(key_padding_mask)
            else:
                attn_mask = attn_mask.masked_fill(key_padding_mask, -1e9)

        if attn_mask is not None and attn_mask.dtype == torch.bool:
            new_attn_mask = torch.zeros_like(attn_mask, dtype=q.dtype)
            new_attn_mask.masked_fill_(attn_mask, -1e9)
            attn_mask = new_attn_mask

        q = q.reshape(n, N * self.num_heads, self.head_dim).transpose(0, 1)
        k = k.reshape(m, N * self.num_heads, self.head_dim).transpose(0, 1)
        v = v.reshape(m, N * self.num_heads, self.head_dim).transpose(0, 1)

        if not training:
            dropout_p = 0.0

        attn_output, attn_output_weights = self._scaled_dot_product_attention(q, k, v, attn_mask, dropout_p)
        attn_output = attn_output.transpose(0, 1).reshape(n, N, embed_dim)
        attn_output = self.out_proj(attn_output)
        attn_output_weights = attn_output_weights.reshape(N, self.num_heads, n, m)
        return attn_output, attn_output_weights

    def _scaled_dot_product_attention(self, q, k, v, attn_mask=None, dropout_p=0.0):
        """
        Args:
            q: (N, n, E), where E is embedding dimension.
            k: (N, m, E)
            v: (N, m, E)
            attn_mask: (n, m) or (N, n, m)
        
        Returns:
            attn_output: (N, n, E)
            attn_weights: (N, n, m)
        """
        q = q / math.sqrt(q.size(2))
        if attn_mask is not None:
            scores = q @ k.transpose(-2, -1) + attn_mask
        else:
            scores = q @ k.transpose(-2, -1)

        attn_weights = F.softmax(scores, dim=-1)
        if dropout_p > 0.0:
            attn_weights = F.dropout(attn_weights, p=dropout_p)
        attn_output = attn_weights @ v
        return attn_output, attn_weights


class MultiHeadSelfAttention(nn.Module):
    def __init__(self, embed_dim, num_heads, dropout=0.1, bias=True):
        super().__init__()
        self.mha = MultiHeadAttention(embed_dim, num_heads, dropout=dropout, bias=bias)

    def forward(self, X, attn_mask=None, key_padding_mask=None):
        """
        Args:
            X (input sequence): (L, N, embed_dim), where L is sequence length.
        """
        return self.mha(X, X, X, attn_mask=attn_mask, key_padding_mask=key_padding_mask)


class PositionalEncoding(nn.Module):
    def __init__(self, d_model=512, dropout=0.1, max_len=1000):
        super().__init__()
        self.dropout = nn.Dropout(dropout)
        self.P = torch.zeros(max_len, d_model)
        row = torch.arange(max_len).reshape(-1, 1)
        col = torch.pow(10000, torch.arange(0, d_model, 2) / d_model)
        self.P[:, ::2] = torch.sin(row / col)
        self.P[:, 1::2] = torch.cos(row / col)
        self.P = self.P.unsqueeze(0).transpose(0, 1)

    def forward(self, X):
        X = X + self.P[:X.shape[0]].to(X.device)
        return self.dropout(X)


class FFN(nn.Module):
    def __init__(self, d_model=512, dim_feedforward=2048, dropout=0.1):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(d_model, dim_feedforward),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(dim_feedforward, d_model),
        )

    def forward(self, X):
        return self.net(X)


class AddNorm(nn.Module):
    def __init__(self, d_model=512, dropout=0.1):
        super().__init__()
        self.dropout = nn.Dropout(dropout)
        self.norm = nn.LayerNorm(d_model)

    def forward(self, X, Y):
        return self.norm(X + self.dropout(Y))


class TransformerEncoderLayer(nn.Module):
    def __init__(self, d_model=512, nhead=8, dim_feedforward=2048, dropout=0.1):
        super().__init__()
        self.self_attn = MultiHeadSelfAttention(d_model, nhead, dropout=dropout)
        self.addnorm1 = AddNorm(d_model, dropout)
        self.ffn = FFN(d_model, dim_feedforward, dropout)
        self.addnorm2 = AddNorm(d_model, dropout)

    def forward(self, src, src_mask=None, src_key_padding_mask=None):
        X = src
        X = self.addnorm1(X, self.self_attn(X, attn_mask=src_mask, key_padding_mask=src_key_padding_mask))
        X = self.addnorm2(X, self.ffn(X))
        return X
