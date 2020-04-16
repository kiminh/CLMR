import os
import torch
from pathlib import Path
import numpy as np

from modules.transformations import AudioTransforms
from .magnatagtune import MTTDataset

def get_mtt_loaders(args, num_workers=16, diff_train_dataset=None):

    train_annotations = (
        Path(args.mtt_processed_annot) / "train_50_tags_annotations_final.csv"
    )
    train_dataset = MTTDataset(
        args, annotations_file=train_annotations, transform=AudioTransforms(args)
    )

    test_annotations = (
        Path(args.mtt_processed_annot) / "test_50_tags_annotations_final.csv"
    )
    test_dataset = MTTDataset(
        args, annotations_file=test_annotations, transform=AudioTransforms(args) 
    )

    train_loader = torch.utils.data.DataLoader(
        dataset=train_dataset,
        batch_size=args.batch_size,
        shuffle=True,
        drop_last=True,
        num_workers=num_workers,
    )

    test_loader = torch.utils.data.DataLoader(
        dataset=test_dataset,
        batch_size=args.batch_size,
        shuffle=False,  # do not shuffle test set
        drop_last=True,
        num_workers=num_workers,
    )

    args.n_classes = args.num_tags
    return train_loader, train_dataset, test_loader, test_dataset