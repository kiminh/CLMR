import os
import torch
import torchaudio
import numpy as np
from collections import defaultdict
from tqdm import tqdm
from utils import parse_args
from data import get_dataset
from model import load_encoder

if __name__ == "__main__":
    args = parse_args("./config/config.yaml", addit=[])
    args.world_size = 1
    args.supervised = False
    args.dataset = "magnatagatune"
    args.device = torch.device(
        "cuda:0" if torch.cuda.is_available() else "cpu")

    args.model_path = "./logs/66"
    args.epoch_num = 10000
    args.finetune_model_path = "./results/66"
    args.finetune_epoch_num = 500

    # data loaders
    (
        train_loader,
        train_dataset,
        val_loader,
        val_dataset,
        test_loader,
        test_dataset,
    ) = get_dataset(args, pretrain=False, download=args.download)

    # load pre-trained encoder
    encoder = load_encoder(args, reload=True)
    encoder.eval()
    encoder = encoder.to(args.device)

    print("LOADED")

    model = None
    if not args.supervised:
        finetuned_head = torch.nn.Sequential(
            torch.nn.Linear(args.n_features, args.n_classes)
        )

        finetuned_head.load_state_dict(
            torch.load(
                os.path.join(
                    args.finetune_model_path,
                    f"finetuner_checkpoint_{args.finetune_epoch_num}.pt",
                ),
                map_location=torch.device('cpu')
            )
        )
        finetuned_head = finetuned_head.to(args.device)
        print("LOADED FINETUNED HEAD")

    # initialize TensorBoard

    args.current_epoch = args.epoch_num

    tag_classes = defaultdict(list)
    predictions = []
    n = 10  # add every n
    with torch.no_grad():
        for step, (track_id, clip_id, segment, fp, label) in enumerate(tqdm(test_dataset.index)):
            if step % n == 0:
                audio = test_dataset.get_full_size_audio(fp)
                audio = audio.to(args.device)
                h = encoder(audio)
                h = torch.nn.functional.softmax(h, dim=1)
                output = finetuned_head(h)
                output = torch.nn.functional.softmax(output, dim=1)

                h = h.mean(dim=0)
<<<<<<< HEAD
                output = output.mean(dim=0) # take mean predictions of whole track, i.e., over batch dim.
                predictions.append([output.cpu().numpy().tolist(), h.cpu().numpy().tolist(), track_id, clip_id, segment, fp, label])
    #             print(step, "/", len(test_dataset))        
=======
                # take mean predictions of whole track, i.e., over batch dim.
                output = output.mean(dim=0)
                predictions.append([output.cpu().numpy().tolist(), h.cpu(
                ).numpy().tolist(), track_id, clip_id, segment, fp, label])

    #             print(step, "/", len(test_dataset))
>>>>>>> 1b0767640feeb8a2229355b6c61adb8a11146d91

    outputs = np.array([o[0] for o in predictions])
    hs = np.array([o[1] for o in predictions])

    # print(outputs.shape, hs.shape)
    # pearson = np.corrcoef(outputs, hs)
    # print(pearson.shape)
    # exit()

    # for website
    print("Preparing .json for web listening interface")
    ds = []
    for idx, a in enumerate(tqdm(predictions)):
        preds_finetuned = a[0]
        preds_encoder = a[1]

        d = {}

        # for faster loading in web browser
        mp3_fp = os.path.splitext(a[5])[0] + ".mp3" # ".wav"
        if not os.path.exists(mp3_fp):
            audio, sr = torchaudio.load(a[5])
            torchaudio.save(mp3_fp, audio, sr)

        d["idx"] = idx
        d["audio"] = mp3_fp

        for ix, p in enumerate(preds_finetuned):
            d[test_dataset.tags[ix]] = p
        for ix, p in enumerate(preds_encoder):
            d[ix] = p

        d["track_id"] = a[2]
        d["clip_id"] = a[3]
        d["segment"] = a[4]

        d["labels"] = []
        for label_id, has_label in enumerate(a[6]):
            if has_label:
                d["labels"].append(test_dataset.tags[label_id])
        ds.append(d)
    #     print(idx, "/", len(predictions))

    import json
<<<<<<< HEAD
    with open("./web/latent_listening/predictions_{}.json".format(args.dataset), "w") as f:
        json.dump(ds, f)
=======
    with open("./web/latent_listening/predictions.json", "w") as f:
        json.dump(ds, f)
>>>>>>> 1b0767640feeb8a2229355b6c61adb8a11146d91
