import argparse
import time
import random
import numpy as np
import torch
from utils import *
import pandas
import os
import warnings
from torch_geometric.loader import DataLoader
import hydra
from augment import augmentation
import wandb

warnings.filterwarnings("ignore")
seed_list = list(range(3407, 10000, 10))

def set_seed(seed=3407):
    os.environ['PYTHONHASHSEED'] = str(seed)
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed(seed)
        torch.cuda.manual_seed_all(seed)
        torch.backends.cudnn.deterministic = True


@hydra.main(config_path='./configs', config_name='config')
def main(cfg):
    print(cfg.gad)
    args = cfg.gad
    setup_wandb(cfg)

    columns = ['name']
    datasets = ['reddit', 'weibo', 'amazon', 'yelp', 'tfinance',
                'elliptic', 'tolokers', 'questions', 'dgraphfin', 'tsocial', 'hetero/amazon', 'hetero/yelp']
    models = model_detector_dict.keys()

    if args.datasets is not None:
        if '-' in args.datasets:
            st, ed = args.datasets.split('-')
            datasets = datasets[int(st):int(ed)+1]
        else:
            datasets = [datasets[int(t)] for t in args.datasets.split(',')]
        print('Evaluated Datasets: ', datasets)
        # only accept int input to indicate the index of datasets

    if args.models is not None:
        models = args.models.split('-')
        print('Evaluated Baselines: ', models)

    for dataset in datasets:
        for metric in ['AUROC mean', 'AUROC std', 'AUPRC mean', 'AUPRC std',
                       'RecK mean', 'RecK std', 'Time']:
            columns.append(dataset + '-' + metric)
    
    results = pandas.DataFrame(columns=columns)
    file_id = None
    for model in models:  # only evaluate gcn for now
        model_result = {'name': model}
        for dataset_name in datasets:  # only test reddit for now
            if model in ['CAREGNN', 'H2FD'] and 'hetero' not in dataset_name:
                continue
            time_cost = 0
            train_config = {
                'device': 'cuda',
                'epochs': 200,
                'patience': 50,
                'metric': 'AUPRC',
                'inductive': args.inductive
            }
            
            # train_config = args.train_config
            # load the initial dataset
            data = GADDataset(dataset_name)

            model_config = {'model': model, 'lr': 0.01, 'drop_rate': 0}

            # model_config = args.model_config
            # model_config['model'] = model

            if dataset_name == 'tsocial':
                model_config['h_feats'] = 16
                # if model in ['GHRN', 'KNNGCN', 'AMNet', 'GT', 'GAT', 'GATv2', 'GATSep', 'PNA']:   # require more than 24G GPU memory
                    # continue

            auc_list, pre_list, rec_list = [], [], []
            for t in range(args.trials):  # set trials to 1
                torch.cuda.empty_cache()
                print("Dataset {}, Model {}, Trial {}".format(dataset_name, model, t))
                data.split(args.semi_supervised, t)
        
                seed = seed_list[t]
                set_seed(seed)
                train_config['seed'] = seed

                # initialize the model
                detector = model_detector_dict[model](cfg, train_config, model_config, data)
                st = time.time()
                print(detector.model)

                # finish training and testing
                if cfg.augment.active:
                    test_score = detector.train_with_augment()
                else:
                    test_score = detector.train()


                auc_list.append(test_score['AUROC'])
                pre_list.append(test_score['AUPRC'])
                rec_list.append(test_score['RecK'])
                ed = time.time()
                time_cost += ed - st
            del detector, data

            model_result[dataset_name + '-AUROC mean'] = np.mean(auc_list)
            model_result[dataset_name + '-AUROC std'] = np.std(auc_list)
            model_result[dataset_name + '-AUPRC mean'] = np.mean(pre_list)
            model_result[dataset_name + '-AUPRC std'] = np.std(pre_list)
            model_result[dataset_name + '-RecK mean'] = np.mean(rec_list)
            model_result[dataset_name + '-RecK std'] = np.std(rec_list)
            model_result[dataset_name + '-Time'] = time_cost / args.trials
            if wandb.run:
                wandb.log({f'{dataset_name}_{model}_AUROC mean': np.mean(auc_list),
                           f'{dataset_name}_{model}_AUROC std': np.std(auc_list),
                           f'{dataset_name}_{model}_AUPRC mean': np.mean(pre_list),
                           f'{dataset_name}_{model}_AUPRC std': np.std(pre_list),
                           f'{dataset_name}_{model}_RecK mean': np.mean(rec_list),
                           f'{dataset_name}_{model}_RecK std': np.std(rec_list),
                           f'{dataset_name}_{model}_Time': time_cost / args.trials})
                
            
        model_result = pandas.DataFrame(model_result, index=[0])
        results = pandas.concat([results, model_result])
        file_id = save_results(results, file_id)
        print(results)


if __name__ == "__main__":
    main()