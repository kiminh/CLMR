import sys
import os
import torch
import torchvision
import numpy as np
import logging
import json
import time

from torch.utils.tensorboard import SummaryWriter

# distributed training
import torch.distributed as dist
import torch.multiprocessing as mp
from torch.nn.parallel import DistributedDataParallel, DataParallel

# custom modules
from data import get_dataset
from model import load_encoder, load_optimizer, save_model
from modules import SimCLR, BYOL, NT_Xent
from modules.sync_batchnorm import convert_model
from solver import Solver
from utils import LogFile, eval_all, write_audio_tb, parse_args, get_log_dir, write_args
from validation import audio_latent_representations


def main(args):

    # data loaders
    (
        train_loader,
        train_dataset,
        val_loader,
        val_dataset,
        test_loader,
        test_dataset,
    ) = get_dataset(args, pretrain=True, download=args.download)

    encoder = load_encoder(args)

    # context model
    # model = BYOL(encoder, args.audio_length) # new!
    model = SimCLR(args, encoder, args.n_features, args.projection_dim)
    model.apply(model.initialize)
    model = model.to(args.device)
    logging.info(model.summary())

    if args.reload:
        model_fp = os.path.join(
            args.reload_path,
            "{}_checkpoint_{}.pt".format(args.model_name, args.epoch_num),
        )
        logging.info(
            f"### RELOADING {args.model_name.upper()} MODEL FROM CHECKPOINT {args.epoch_num} ###"
        )
        model.load_state_dict(torch.load(model_fp, map_location=args.device.type))
        args.start_epoch = args.epoch_num

    # optimizer / scheduler
    optimizer, scheduler = load_optimizer(args, model)

    if not args.supervised:
        criterion = NT_Xent(
            args.batch_size, args.temperature, args.device, args.world_size
        )
    else:
        criterion = torch.nn.BCEWithLogitsLoss()

    # DDP
    if args.dataparallel:
        if not args.supervised:
            model = convert_model(model)
        model = DataParallel(model)
        model = model.to(args.device)
    elif args.world_size > 1:
        model = torch.nn.SyncBatchNorm.convert_sync_batchnorm(model)
        model = DistributedDataParallel(
            model, device_ids=[args.local_rank], output_device=args.local_rank
        )

    writer = None
    if args.is_master:
        writer = SummaryWriter(log_dir=args.model_path)

    # save random init. model
    if not args.reload:
        args.current_epoch = "random"
        save_model(args, model, optimizer, args.model_name)

        # write a few audio files to TensorBoard for comparison
        # write_audio_tb(args, train_loader, test_loader, writer)

    # start training
    solver = Solver(model, optimizer, criterion, writer)

    if args.supervised:
        validate_idx = 1
    else:
        validate_idx = 50

    args.current_epoch = args.start_epoch
    last_model = None
    last_auc = 0
    last_ap = 0
    early_stop = 0
    initial_lr = optimizer.param_groups[0]["lr"]
    warmup_lr = [idx*initial_lr/args.warmup_epochs for idx in range(1, args.warmup_epochs+1)]
    for epoch in range(args.start_epoch, args.epochs):
        t0 = time.time()
        if args.world_size > 1:
            dist.barrier()

        # if epoch % validate_idx == 0:
        #     audio_latent_representations(
        #         args,
        #         train_loader.dataset,
        #         model,
        #         args.current_epoch,
        #         args.global_step,
        #         writer,
        #         train=True,
        #     )
        #     audio_latent_representations(
        #         args,
        #         test_loader.dataset,
        #         model,
        #         args.current_epoch,
        #         args.global_step,
        #         writer,
        #         train=False,
        #     )
        
        if args.optimizer == "LARS":
            if epoch < args.warmup_epochs:
                optimizer.param_groups[0]["lr"] = warmup_lr[epoch]
            elif epoch == args.warmup_epochs:
                optimizer.param_groups[0]["lr"] = initial_lr
        
        learning_rate = optimizer.param_groups[0]["lr"]
        metrics = solver.train(args, train_loader)

        if args.is_master:
            for k, v in metrics.items():
                writer.add_scalar(k, v, epoch)
            writer.add_scalar("Misc/learning_rate", learning_rate, epoch)
            logging.info(
                f"Epoch [{epoch}/{args.epochs}]\t Loss: {metrics['Loss/train']}\t lr: {round(learning_rate, 5)}"
            )

        if epoch > 0 and epoch % validate_idx == 0 or early_stop > 0:
            metrics = solver.validate(args, val_loader)

            # early stopping for supervised
            if args.supervised:
                if metrics["AUC_tag/test"] < last_auc and metrics["AP_tag/test"] < last_ap:
                    last_model = model
                    early_stop += 1
                    logging.info(
                        "Early stop count: {}\t\t{} (best: {})\t {} (best: {})".format(
                            early_stop,
                            metrics["AUC_tag/test"],
                            last_auc,
                            metrics["AP_tag/test"],
                            last_ap,
                        )
                    )
                else:
                    last_auc = metrics["AUC_tag/test"]
                    last_ap = metrics["AP_tag/test"]
                    early_stop = 0

            if args.is_master:
                for k, v in metrics.items():
                    writer.add_scalar(k, v, epoch)
                    logging.info(f"[Test] Epoch [{epoch}/{args.epochs}]\t {k}: {v}")

        if args.is_master and epoch > 0 and epoch % args.checkpoint_epochs == 0:
            save_model(args, model, optimizer, name=args.model_name)
        
        if args.is_master and args.optimizer == "LARS" and args.current_epoch >= args.warmup_epochs:
            scheduler.step()

        args.current_epoch += 1
        print(f"Time: {time.time() - t0}")
        
        if args.supervised and early_stop >= 3:
            logging.info("Early stopping...")
            break


    save_model(args, model, optimizer, name=args.model_name)

    if args.supervised:
        if last_model is None:
            logging.info("No early stopping, using last model")
            last_model = model

        # eval all
        metrics = eval_all(
            args, test_loader, encoder, last_model, writer, n_tracks=None
        )
        logging.info("### Final tag/clip ROC-AUC/PR-AUC scores ###")
        m = {}
        for k, v in metrics.items():
            if "hparams" in k:
                logging.info(f"[Test average AUC/AP]: {k}, {v}")
                m[k] = v
            else:
                for tag, val in zip(test_loader.dataset.tags, v):
                    logging.info(f"[Test {k}]\t\t{tag}\t{val}")
                    m[k + "/" + tag] = val

        with open(os.path.join(args.model_path, "results.json"), "w") as f:
            json.dump(m, f)

    ## end training


if __name__ == "__main__":
    args = parse_args()
    args.reload_path = args.model_path

    if "WORLD_SIZE" not in os.environ.keys():
        args.world_size = 1
        args.model_path = get_log_dir("./logs", args.id)
    else:
        args.world_size = int(os.environ["WORLD_SIZE"])
        dist.init_process_group(backend="nccl", init_method="env://")
        args.model_path = os.path.join("./logs", str(args.id))
        if not os.path.exists(args.model_path):
            os.makedirs(args.model_path)

    print("World size", args.world_size)

    args.num_gpus = torch.cuda.device_count()

    # dataparallel splits the data across the batch dimension
    if args.dataparallel:
        # args.batch_size *= args.num_gpus
        print(f"DP batch size: {args.batch_size}")

    args.is_master = args.local_rank == 0

    # set the device
    args.device = torch.device(args.local_rank)
    # args.device = torch.device(f"cuda:{args.local_rank}" if torch.cuda.is_available() else "cpu")
    print("Device", args.device)

    print("Num devices", args.num_gpus)

    if args.world_size > 1:
        torch.cuda.set_device(args.local_rank)

    torch.cuda.manual_seed_all(args.seed)
    np.random.seed(args.seed)

    args.global_step = 0
    args.current_epoch = 0

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(os.path.join(args.model_path, "output.log")),
            logging.StreamHandler(),
        ],
    )

    write_args(args)
    main(args)
