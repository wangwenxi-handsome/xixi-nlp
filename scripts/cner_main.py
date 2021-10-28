import os
import sys
sys.path.append(os.getcwd())
import torch
import torch.optim as optim
from dataloader.preprocessor.cner import CNERPreProcessor
from model.BertLinerSoftmax import BertLinerSoftmax
from worker.worker import Worker
from utils.torch_related import setup_seed, get_torch_model
from metric.ner_metric import NERMetric
from utils.torch_related import get_linear_schedule_with_warmup


# 实验中用到的参数，用于实验
global_config = {
    "epoch": 3,
    "model_name": "bert-base-chinese",
    "data_folder_name ": "product/data/cner",
    "label_num": 25,
    "lr": 3e-05,
    "folder_path": "product/experiments/cner1/",
    "batch_size_per_gpu": 24,
}


def train(config, data_gen, train_dataloader, dev_dataloader = None):
    # model
    device, model = get_torch_model(
        BertLinerSoftmax, 
        model_config = {"model_name": config["model_name"], "loss_func": "ce", "label_num": config["label_num"]},
        load_checkpoint_path = None,
    )

    # opt
    no_decay = ["bias", "LayerNorm.weight"]
    optimizer_grouped_parameters = [
        {"params": [p for n, p in model.named_parameters() if not any(nd in n for nd in no_decay)],
        "weight_decay": 0.01,},
        {"params": [p for n, p in model.named_parameters() if any(nd in n for nd in no_decay)], "weight_decay": 0.0},
    ]
    optimizer = optim.AdamW(optimizer_grouped_parameters, lr = config["lr"], eps = 1e-08)
    scheduler = get_linear_schedule_with_warmup(optimizer, num_warmup_steps = 24, num_training_steps = 240.0)

    # worker
    trainer = Worker(
        device = device,
        model = model, 
        folder_path = config["folder_path"],
        epoch = config["epoch"],
        optimizer = optimizer, 
        scheduler = scheduler,
    )
    trainer.train(train_dataloader, dev_dataloader)
    del trainer


def rollout(config, data_gen, dataloader, name, checkpoint = None):
    metrics = []
    if checkpoint is None:
        all_checkpoints = os.listdir(os.path.join(config["folder_name"], "/model/"))
        all_checkpoints = [os.path.join(config["folder_name"], i) for i in all_checkpoints]
    elif isinstance(checkpoint, str):
        all_checkpoints = [checkpoint]
    elif isinstance(checkpoint, list):
        all_checkpoints = checkpoint
    else:
        raise ValueError(f"{type(checkpoint)} is not supported")

    for checkpoint in all_checkpoints:
        device, model = get_torch_model(
            BertLinerSoftmax, 
            model_config = {"model_name": config["model_name"], "loss_func": "ce", "label_num": config["label_num"]},
            load_checkpoint_path = checkpoint,
        )

            # worker
        trainer = Worker(
            device = device,
            model = model, 
        )

        outputs, _ = trainer.rollout(dataloader)
        entity_outputs, entity_labels, offset_outputs = data_gen.decode(
            outputs, 
            data_gen.get_tokenize_length(name), 
            data_gen.get_raw_data_y(name),
        )
        metric = NERMetric(data_gen.get_raw_data_x(name), entity_labels, entity_outputs)
        metrics.append(metric)


def main(config):
    setup_seed(42)

    # data
    n_gpus = max(torch.cuda.device_count(), 1)
    data_gen = CNERPreProcessor(model_name = config["model_name"])
    data_gen.init_data(folder_name = config["data_folder_name"])
    dataloader = data_gen.get_dataloader(batch_size = config["batch_size_per_gpu"] * n_gpus)

    # train
    train(config, data_gen, dataloader["train"], dataloader["dev"])

    # test
    rollout(config, data_gen, dataloader["test"], "test")


if __name__ == "__main__":
    main(global_config)