import os
import copy
import inspect
from tqdm import tqdm
import torch
import torch.nn as nn


class Worker:
    """train and rollout.
    """
    def __init__(
        self, 
        model: nn.Module = None,
        dataloader = {},
        optimizer = None, 
        loss_func = None,
        if_by_state_dict: bool = False,
        load_checkpoint_path: str = None,
        save_checkpoint_path: str = None,
        epoch = 50,
    ):
        # train kwargs
        self.epoch = epoch

        # data
        self.train_dataloader = dataloader.get("train", None)
        self.dev_dataloader = dataloader.get("dev", None)
        self.test_dataloader = dataloader.get("test", None)

        # torch related. model, loss, opt with device.
        self.device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
        self.loss_func = loss_func
        self.opt = optimizer
        self.if_by_state_dict = if_by_state_dict
        self.save_checkpoint_path = save_checkpoint_path
        self.load_model(model, load_checkpoint_path, if_by_state_dict)

        # early stop
        self.best_loss = None
        self.best_loss_epoch = None
        self.best_model = None

    def train(self):
        for e in range(self.epoch):
            print(f"This is epoch{e}#")
            step = 0
            accum_loss = 0
            for data in tqdm(self.train_dataloader):
                # zero grad
                self.opt.zero_grad()

                # model forward
                model_kwargs = dict(inspect.signature(self.model.forward).parameters)
                model_kwargs = {i: data[i].to(self.device) for i in model_kwargs}
                labels = data["labels"].to(self.device)
                output = self.model(**model_kwargs)

                # get loss and step
                loss = self.loss_func(output.contiguous().view(-1, self.model.label_num), labels.contiguous().view(-1))
                loss.backward()
                self.opt.step()

                # print loss every 1/5
                step += 1
                accum_loss += loss
                if step % int(len(self.train_dataloader) / 5) == 0:
                    print(f"train loss is {accum_loss / int(len(self.train_dataloader) / 5)}")
                    step = 0
                    accum_loss = 0

            # valid
            valid_loss, _ = self.rollout(self.dev_dataloader)
            # if best model
            if self.best_loss is None or valid_loss < self.best_loss:
                self.best_loss = valid_loss
                self.best_loss_epoch = e
                self.best_model = copy.deepcopy(self.model).cpu()
            elif e - self.best_loss_epoch > 2:
                if self.save_checkpoint_path is not None:
                    # save model
                    if not os.path.exists(self.save_checkpoint_path):
                        os.mkdir(self.save_checkpoint_path)
                    self.save_model(self.best_model, os.path.join(self.save_checkpoint_path, f"{self.best_loss_epoch}.pth"))
                break

    def rollout(self, dataloader):
        outputs = []
        if_compute_loss = False
        # model forward to get outputs
        with torch.no_grad():
            self.model.eval()
            loss = 0
            for data in dataloader:
                # model forward
                model_kwargs = dict(inspect.signature(self.model.forward).parameters)
                model_kwargs = {i: data[i].to(self.device) for i in model_kwargs}
                output = self.model(**model_kwargs)
                outputs.append(output.cpu())
                if (self.loss_func is not None) and ("labels" in data):
                    if_compute_loss = True
                    labels = data["labels"].to(self.device)
                    loss += self.loss_func(output.contiguous().view(-1, self.model.label_num), labels.contiguous().view(-1))
            self.model.train()
        
        # return loss(None is no loss_func) and outputs
        if if_compute_loss:
            loss /= len(dataloader)
            print(f"valid loss is {loss}")
        else:
            loss = None
        return loss, outputs

    def load_model(self, model, load_checkpoint_path, if_by_state_dict):
        """load_checkpoint_path have high prority.
        """
        # init model
        if load_checkpoint_path is None:
            self.model = model
        # load model from state_dict
        elif if_by_state_dict:
            self.model = model
            self.model.load_state_dict(torch.load(load_checkpoint_path, map_location=self.device))
        # load model from pth
        else:
            self.model = torch.load(load_checkpoint_path)
        self.model.to(self.device)

    def save_model(self, model, save_path):
        # if_by_state_dict applied to save and load means 从哪里来就到哪里去
        if self.if_by_state_dict:
            torch.save(model.state_dict(), save_path)
        else:
            torch.save(model, save_path)

    def updata_train_kwargs(
        self, 
        save_checkpoint_path = None, 
        train_dataloader = None, 
        dev_dataloader = None,
        opt = None,
        loss_func = None,
    ):
        if save_checkpoint_path is not None:
            self.save_checkpoint_path = save_checkpoint_path
        if train_dataloader is not None:
            self.train_dataloader = train_dataloader
        if dev_dataloader is not None:
            self.dev_dataloader = dev_dataloader
        if opt is not None:
            self.opt = opt
        if loss_func is not None:
            self.loss_func = nn.CrossEntropyLoss(ignore_index=0)