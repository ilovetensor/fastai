# AUTOGENERATED! DO NOT EDIT! File to edit: ../../nbs/19_callback.mixup.ipynb.

# %% ../../nbs/19_callback.mixup.ipynb 2
from __future__ import annotations
from ..basics import *
from torch.distributions.beta import Beta

# %% auto 0
__all__ = ['reduce_loss', 'MixHandler', 'MixUp', 'CutMix']

# %% ../../nbs/19_callback.mixup.ipynb 6
def reduce_loss(
    loss:Tensor, 
    reduction:str='mean' # PyTorch loss reduction
)->Tensor:
    "Reduce the loss based on `reduction`"
    return loss.mean() if reduction == 'mean' else loss.sum() if reduction == 'sum' else loss

# %% ../../nbs/19_callback.mixup.ipynb 7
class MixHandler(Callback):
    "A handler class for implementing `MixUp` style scheduling"
    run_valid = False
    def __init__(self, 
        alpha:float=0.5 # Determine `Beta` distribution in range (0.,inf]
    ):
        self.distrib = Beta(tensor(alpha), tensor(alpha))

    def before_train(self):
        "Determine whether to stack y"
        self.stack_y = getattr(self.learn.loss_func, 'y_int', False)
        if self.stack_y: self.old_lf,self.learn.loss_func = self.learn.loss_func,self.lf

    def after_train(self):
        "Set the loss function back to the previous loss"
        if self.stack_y: self.learn.loss_func = self.old_lf

    def after_cancel_train(self):
        "If training is canceled, still set the loss function back"
        self.after_train()

    def after_cancel_fit(self):
        "If fit is canceled, still set the loss function back"
        self.after_train()

    def lf(self, pred, *yb):
        "lf is a loss function that applies the original loss function on both outputs based on `self.lam`"
        if not self.training: return self.old_lf(pred, *yb)
        with NoneReduce(self.old_lf) as lf:
            loss = torch.lerp(lf(pred,*self.yb1), lf(pred,*yb), self.lam)
        return reduce_loss(loss, getattr(self.old_lf, 'reduction', 'mean'))

# %% ../../nbs/19_callback.mixup.ipynb 10
class MixUp(MixHandler):
    "Implementation of https://arxiv.org/abs/1710.09412"
    def __init__(self, 
        alpha:float=.4 # Determine `Beta` distribution in range (0.,inf]
    ): 
        super().__init__(alpha)
        
    def before_batch(self):
        "Blend xb and yb with another random item in a second batch (xb1,yb1) with `lam` weights"
        lam = self.distrib.sample((self.y.size(0),)).squeeze().to(self.x.device)
        lam = torch.stack([lam, 1-lam], 1)
        self.lam = lam.max(1)[0]
        shuffle = torch.randperm(self.y.size(0)).to(self.x.device)
        xb1,self.yb1 = tuple(L(self.xb).itemgot(shuffle)),tuple(L(self.yb).itemgot(shuffle))
        nx_dims = len(self.x.size())
        self.learn.xb = tuple(L(xb1,self.xb).map_zip(torch.lerp,weight=unsqueeze(self.lam, n=nx_dims-1)))

        if not self.stack_y:
            ny_dims = len(self.y.size())
            self.learn.yb = tuple(L(self.yb1,self.yb).map_zip(torch.lerp,weight=unsqueeze(self.lam, n=ny_dims-1)))

# %% ../../nbs/19_callback.mixup.ipynb 21
class CutMix(MixHandler): 
    "Implementation of https://arxiv.org/abs/1905.04899"
    def __init__(self, 
        alpha:float=1. # Determine `Beta` distribution in range (0.,inf]
    ): 
        super().__init__(alpha)
        
    def before_batch(self):
        "Add `rand_bbox` patches with size based on `lam` and location chosen randomly."
        bs, _, H, W = self.x.size()
        self.lam = self.distrib.sample((1,)).to(self.x.device)
        shuffle = torch.randperm(bs).to(self.x.device)
        xb1,self.yb1 = self.x[shuffle], tuple((self.y[shuffle],))
        x1, y1, x2, y2 = self.rand_bbox(W, H, self.lam)
        self.learn.xb[0][..., y1:y2, x1:x2] = xb1[..., y1:y2, x1:x2]
        self.lam = (1 - ((x2-x1)*(y2-y1))/float(W*H))
        if not self.stack_y:
            ny_dims = len(self.y.size())
            self.learn.yb = tuple(L(self.yb1,self.yb).map_zip(torch.lerp,weight=unsqueeze(self.lam, n=ny_dims-1)))

    def rand_bbox(self, 
        W:int, # Width bbox will be
        H:int, # Height bbox will be
        lam:Tensor # lambda sample from Beta distribution i.e tensor([0.3647])
    )->tuple: # Represents the top-left pixel location and the bottom-right pixel location
        "Give a bounding box location based on the size of the im and a weight"
        cut_rat = torch.sqrt(1. - lam).to(self.x.device)
        cut_w = torch.round(W * cut_rat).type(torch.long).to(self.x.device)
        cut_h = torch.round(H * cut_rat).type(torch.long).to(self.x.device)
        # uniform
        cx = torch.randint(0, W, (1,)).to(self.x.device)
        cy = torch.randint(0, H, (1,)).to(self.x.device)
        x1 = torch.clamp(cx - cut_w // 2, 0, W)
        y1 = torch.clamp(cy - cut_h // 2, 0, H)
        x2 = torch.clamp(cx + cut_w // 2, 0, W)
        y2 = torch.clamp(cy + cut_h // 2, 0, H)
        return x1, y1, x2, y2