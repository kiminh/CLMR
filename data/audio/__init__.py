from .librispeech import LibriDataset
from .magnatagatune import MTTDataset
from .millionsongdataset import MSDDataset
from .fma import FmaDataset
from .gtzan import GTZANDataset
from .birdsong import BirdsongDataset

datasets = {
    "librispeech": LibriDataset,
    "magnatagatune": MTTDataset,
    "msd": MSDDataset,
    "fma": FmaDataset,
    "gtzan": GTZANDataset,
    "birdsong": BirdsongDataset,
}