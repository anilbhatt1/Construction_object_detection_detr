# Copyright (c) Facebook, Inc. and its affiliates. All Rights Reserved
"""
DETR Transformer class.

Copy-paste from torch.nn.Transformer with modifications:
    * positional encodings are passed in MHattention
    * extra LN at the end of encoder is removed
    * decoder returns a stack of activations from all decoding layers
"""
import copy
from typing import Optional, List

import torch
import torch.nn.functional as F
from torch import nn, Tensor


class Transformer(nn.Module):

    def __init__(self, d_model=512, nhead=8, num_encoder_layers=6,
                 num_decoder_layers=6, dim_feedforward=2048, dropout=0.1,
                 activation="relu", normalize_before=False,
                 return_intermediate_dec=False):
        super().__init__()

        encoder_layer = TransformerEncoderLayer(d_model, nhead, dim_feedforward,
                                                dropout, activation, normalize_before)
        encoder_norm = nn.LayerNorm(d_model) if normalize_before else None
        self.encoder = TransformerEncoder(encoder_layer, num_encoder_layers, encoder_norm)

        decoder_layer = TransformerDecoderLayer(d_model, nhead, dim_feedforward,
                                                dropout, activation, normalize_before)
        decoder_norm = nn.LayerNorm(d_model)
        self.decoder = TransformerDecoder(decoder_layer, num_decoder_layers, decoder_norm,
                                          return_intermediate=return_intermediate_dec)

        self._reset_parameters()

        self.d_model = d_model
        self.nhead = nhead

    def _reset_parameters(self):
        for p in self.parameters():
            if p.dim() > 1:
                nn.init.xavier_uniform_(p)

    def forward(self, src, mask, query_embed, pos_embed, print_flag):
        # flatten NxCxHxW to HWxNxC
        bs, c, h, w = src.shape
        if print_flag:
            print(f'Transformer FWD : {src.shape}')
        src = src.flatten(2).permute(2, 0, 1)
        if print_flag: 
            print(f'Transformer FWD after src.flatten(2).permute(2, 0, 1) : {src.shape}')
        pos_embed = pos_embed.flatten(2).permute(2, 0, 1)
        if print_flag:
            print(f'Transformer FWD after pos_embed.flatten(2).permute(2, 0, 1) : {pos_embed.shape}')
        query_embed = query_embed.unsqueeze(1).repeat(1, bs, 1)
        if print_flag:
            print(f'Transformer FWD after query_embed.unsqueeze(1).repeat(1, bs, 1) : {query_embed.shape}')
        mask = mask.flatten(1)

        tgt = torch.zeros_like(query_embed)
        if print_flag: 
            print(f'Transformer FWD tgt.size() - after torch.zeros_like(query_embed) : {tgt.size()}') 
        memory = self.encoder(src, src_key_padding_mask=mask, pos=pos_embed, print_flag=print_flag)
        if print_flag:
            print(f'Transformer FWD memory.size() - o/p of self.encoder : {memory.size()}')  
        hs = self.decoder(tgt, memory, memory_key_padding_mask=mask,
                          pos=pos_embed, query_pos=query_embed, print_flag=print_flag)
        if print_flag:
            print(f'Transformer FWD hs.size() - o/p of self.decoder : {hs.size()}') 
        return hs.transpose(1, 2), memory.permute(1, 2, 0).view(bs, c, h, w)


class TransformerEncoder(nn.Module):

    def __init__(self, encoder_layer, num_layers, norm=None):
        super().__init__()
        self.layers = _get_clones(encoder_layer, num_layers)
        self.num_layers = num_layers
        self.norm = norm

    def forward(self, src,
                mask: Optional[Tensor] = None,
                src_key_padding_mask: Optional[Tensor] = None,
                pos: Optional[Tensor] = None, print_flag=0):
        output = src
        if print_flag: 
            print(f'TransformerEncoder FWD Entering - output.size() : {output.size()}, src.size() : {src.size()}') 
        
        lyr = 0
        for layer in self.layers:
            lyr += 1  
            if print_flag:
                print(f'TransformerEncoder FWD Layer # {lyr}')
            output = layer(output, src_mask=mask,
                           src_key_padding_mask=src_key_padding_mask, pos=pos, lyr=lyr, print_flag=print_flag)

        if self.norm is not None:
            output = self.norm(output)
        if print_flag:
            print(f'TransformerEncoder FWD - output.size() : {output.size()}')
        return output


class TransformerDecoder(nn.Module):

    def __init__(self, decoder_layer, num_layers, norm=None, return_intermediate=False):
        super().__init__()
        self.layers = _get_clones(decoder_layer, num_layers)
        self.num_layers = num_layers
        self.norm = norm
        self.return_intermediate = return_intermediate
      
    def forward(self, tgt, memory,
                tgt_mask: Optional[Tensor] = None,
                memory_mask: Optional[Tensor] = None,
                tgt_key_padding_mask: Optional[Tensor] = None,
                memory_key_padding_mask: Optional[Tensor] = None,
                pos: Optional[Tensor] = None,
                query_pos: Optional[Tensor] = None,
                print_flag=0):
        output = tgt

        intermediate = []

        lyr = 0
        for layer in self.layers:
            lyr += 1
            if print_flag:
                print(f'TransformerDecoder FWD Layer # {lyr}')
            output = layer(output, memory, tgt_mask=tgt_mask,
                           memory_mask=memory_mask,
                           tgt_key_padding_mask=tgt_key_padding_mask,
                           memory_key_padding_mask=memory_key_padding_mask,
                           pos=pos, query_pos=query_pos, lyr = lyr, print_flag=print_flag)
            if self.return_intermediate:
                intermediate.append(self.norm(output))
       
        if self.norm is not None:
            output = self.norm(output)
            if self.return_intermediate:
                intermediate.pop()
                intermediate.append(output)
        
        if print_flag:
            print(f'TransformerDecoder FWD - len(intermediate) : {len(intermediate)}')
        if self.return_intermediate:
            interm_ = torch.stack(intermediate)
            if print_flag:
                print(f'TransformerDecoder FWD - torch.stack(intermediate).size() : {interm_.size()}')
            return torch.stack(intermediate)
         
        return output.unsqueeze(0)


class TransformerEncoderLayer(nn.Module):

    def __init__(self, d_model, nhead, dim_feedforward=2048, dropout=0.1,
                 activation="relu", normalize_before=False):
        super().__init__()
        self.self_attn = nn.MultiheadAttention(d_model, nhead, dropout=dropout)
        # Implementation of Feedforward model
        self.linear1 = nn.Linear(d_model, dim_feedforward)
        self.dropout = nn.Dropout(dropout)
        self.linear2 = nn.Linear(dim_feedforward, d_model)

        self.norm1 = nn.LayerNorm(d_model)
        self.norm2 = nn.LayerNorm(d_model)
        self.dropout1 = nn.Dropout(dropout)
        self.dropout2 = nn.Dropout(dropout)

        self.activation = _get_activation_fn(activation)
        self.normalize_before = normalize_before

    def with_pos_embed(self, tensor, pos: Optional[Tensor]):
        return tensor if pos is None else tensor + pos

    def forward_post(self,
                     src,
                     src_mask: Optional[Tensor] = None,
                     src_key_padding_mask: Optional[Tensor] = None,
                     pos: Optional[Tensor] = None,
                     lyr = 0, print_flag=0):
        q = k = self.with_pos_embed(src, pos)
        if lyr == 1 and print_flag:
            print(f'TEL forward_post {lyr} q : {q.size()}, k : {k.size()}')
        src2 = self.self_attn(q, k, value=src, attn_mask=src_mask,
                              key_padding_mask=src_key_padding_mask)[0]
        if lyr == 1 and print_flag:
            print(f'TEL forward_post {lyr} after self_attn - src2 : {src2.size()}')
        src = src + self.dropout1(src2)
        src = self.norm1(src)
        src2 = self.linear2(self.dropout(self.activation(self.linear1(src))))
        src = src + self.dropout2(src2)
        src = self.norm2(src)
        if lyr == 1 and print_flag:
            print(f'TEL forward_post {lyr} src post +drop1(src2), norm1(src), [linear1, activ, drop, linear2](src), +drop2(src), norm-2(src): {src.size()}')  
        return src

    def forward_pre(self, src,
                    src_mask: Optional[Tensor] = None,
                    src_key_padding_mask: Optional[Tensor] = None,
                    pos: Optional[Tensor] = None):
        src2 = self.norm1(src)
        q = k = self.with_pos_embed(src2, pos)
        src2 = self.self_attn(q, k, value=src2, attn_mask=src_mask,
                              key_padding_mask=src_key_padding_mask)[0]
        src = src + self.dropout1(src2)
        src2 = self.norm2(src)
        src2 = self.linear2(self.dropout(self.activation(self.linear1(src2))))
        src = src + self.dropout2(src2)
        return src

    def forward(self, src,
                src_mask: Optional[Tensor] = None,
                src_key_padding_mask: Optional[Tensor] = None,
                pos: Optional[Tensor] = None,
                lyr = 0, print_flag=0):
        if lyr == 1 and print_flag:
            print(f'TEL forward {lyr} src : {src.size()}, pos : {pos.size()}')
        if self.normalize_before:
            return self.forward_pre(src, src_mask, src_key_padding_mask, pos)
        return self.forward_post(src, src_mask, src_key_padding_mask, pos, lyr, print_flag)


class TransformerDecoderLayer(nn.Module):

    def __init__(self, d_model, nhead, dim_feedforward=2048, dropout=0.1,
                 activation="relu", normalize_before=False):
        super().__init__()
        self.self_attn = nn.MultiheadAttention(d_model, nhead, dropout=dropout)
        self.multihead_attn = nn.MultiheadAttention(d_model, nhead, dropout=dropout)
        # Implementation of Feedforward model
        self.linear1 = nn.Linear(d_model, dim_feedforward)
        self.dropout = nn.Dropout(dropout)
        self.linear2 = nn.Linear(dim_feedforward, d_model)

        self.norm1 = nn.LayerNorm(d_model)
        self.norm2 = nn.LayerNorm(d_model)
        self.norm3 = nn.LayerNorm(d_model)
        self.dropout1 = nn.Dropout(dropout)
        self.dropout2 = nn.Dropout(dropout)
        self.dropout3 = nn.Dropout(dropout)

        self.activation = _get_activation_fn(activation)
        self.normalize_before = normalize_before

    def with_pos_embed(self, tensor, pos: Optional[Tensor]):
        return tensor if pos is None else tensor + pos

    def forward_post(self, tgt, memory,
                     tgt_mask: Optional[Tensor] = None,
                     memory_mask: Optional[Tensor] = None,
                     tgt_key_padding_mask: Optional[Tensor] = None,
                     memory_key_padding_mask: Optional[Tensor] = None,
                     pos: Optional[Tensor] = None,
                     query_pos: Optional[Tensor] = None,
                     lyr = 0, print_flag=0):
        if lyr == 1 and print_flag:
            print(f'TDL forward_post {lyr} tgt.size() : {tgt.size()}, memory.size() : {memory.size()}, pos.size() : {pos.size()}, query_pos.size : {query_pos.size()}') 
        q = k = self.with_pos_embed(tgt, query_pos)
        if lyr == 1 and print_flag:
            print(f'TDL forward_post {lyr} q : {q.size()}, k : {k.size()}')
        tgt2 = self.self_attn(q, k, value=tgt, attn_mask=tgt_mask,
                              key_padding_mask=tgt_key_padding_mask)[0]
        if lyr == 1 and print_flag:
            print(f'TDL forward_post {lyr} tgt2 - after self_attn : {tgt2.size()}')
        tgt = tgt + self.dropout1(tgt2)
        tgt = self.norm1(tgt)
        tgt2 = self.multihead_attn(query=self.with_pos_embed(tgt, query_pos),
                                   key=self.with_pos_embed(memory, pos),
                                   value=memory, attn_mask=memory_mask,
                                   key_padding_mask=memory_key_padding_mask)[0]
        if lyr == 1 and print_flag:
            print(f'TDL forward_post {lyr} tgt2 - after multiheadattn : {tgt2.size()}')
        tgt = tgt + self.dropout2(tgt2)
        tgt = self.norm2(tgt)
        tgt2 = self.linear2(self.dropout(self.activation(self.linear1(tgt))))
        tgt = tgt + self.dropout3(tgt2)
        tgt = self.norm3(tgt)
        if lyr == 1 and print_flag:
            print(f'TDL forward_post {lyr} tgt - after dropouts, linear, activations & norms : {tgt.size()}')
        return tgt

    def forward_pre(self, tgt, memory,
                    tgt_mask: Optional[Tensor] = None,
                    memory_mask: Optional[Tensor] = None,
                    tgt_key_padding_mask: Optional[Tensor] = None,
                    memory_key_padding_mask: Optional[Tensor] = None,
                    pos: Optional[Tensor] = None,
                    query_pos: Optional[Tensor] = None):
        tgt2 = self.norm1(tgt)
        q = k = self.with_pos_embed(tgt2, query_pos)
        tgt2 = self.self_attn(q, k, value=tgt2, attn_mask=tgt_mask,
                              key_padding_mask=tgt_key_padding_mask)[0]
        tgt = tgt + self.dropout1(tgt2)
        tgt2 = self.norm2(tgt)
        tgt2 = self.multihead_attn(query=self.with_pos_embed(tgt2, query_pos),
                                   key=self.with_pos_embed(memory, pos),
                                   value=memory, attn_mask=memory_mask,
                                   key_padding_mask=memory_key_padding_mask)[0]
        tgt = tgt + self.dropout2(tgt2)
        tgt2 = self.norm3(tgt)
        tgt2 = self.linear2(self.dropout(self.activation(self.linear1(tgt2))))
        tgt = tgt + self.dropout3(tgt2)
        return tgt

    def forward(self, tgt, memory,
                tgt_mask: Optional[Tensor] = None,
                memory_mask: Optional[Tensor] = None,
                tgt_key_padding_mask: Optional[Tensor] = None,
                memory_key_padding_mask: Optional[Tensor] = None,
                pos: Optional[Tensor] = None,
                query_pos: Optional[Tensor] = None, 
                lyr = 0, print_flag=0):
        if self.normalize_before:
            return self.forward_pre(tgt, memory, tgt_mask, memory_mask,
                                    tgt_key_padding_mask, memory_key_padding_mask, pos, query_pos)
        if lyr == 1 and print_flag:
            print(f'TDL forward {lyr} tgt : {tgt.size()}, memory : {memory.size()}, tgt_mask : {type(tgt_mask)}, pos : {pos.size()}, query_pos : {query_pos.size()}')
        return self.forward_post(tgt, memory, tgt_mask, memory_mask,
                                 tgt_key_padding_mask, memory_key_padding_mask, pos, query_pos, lyr, print_flag)


def _get_clones(module, N):
    return nn.ModuleList([copy.deepcopy(module) for i in range(N)])


def build_transformer(args):
    print(f'Transformer BUILD - d_model / args.hidden_dim : {args.hidden_dim}, dropout /args.dropout : {args.dropout}, nhead / args.nheads : {args.nheads}')
    print(f'Transformer BUILD - dim_feedforward : {args.dim_feedforward}, num_encoder_layers : {args.enc_layers}, num_decoder_layers : {args.dec_layers}')
    print(f'Transformer BUILD - normalize_before : {args.pre_norm}')
    return Transformer(
        d_model=args.hidden_dim,
        dropout=args.dropout,
        nhead=args.nheads,
        dim_feedforward=args.dim_feedforward,
        num_encoder_layers=args.enc_layers,
        num_decoder_layers=args.dec_layers,
        normalize_before=args.pre_norm,
        return_intermediate_dec=True,
    )


def _get_activation_fn(activation):
    """Return an activation function given a string"""
    if activation == "relu":
        return F.relu
    if activation == "gelu":
        return F.gelu
    if activation == "glu":
        return F.glu
    raise RuntimeError(F"activation should be relu/gelu, not {activation}.")
