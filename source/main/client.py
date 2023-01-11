
import os, sys
__dir__ = os.path.dirname(os.path.abspath(__file__))
sys.path.append(__dir__), sys.path.append(os.path.abspath(os.path.join(__dir__, "..")))
from libs import *

from strategies import FedAvg
from data import ImageDataset
from models.cnn import *
from engines import client_fit_fn

class Client(fl.client.NumPyClient):
    def __init__(self, 
        fit_loaders, num_epochs, 
        client_model, 
        optimizer, 
        lr_scheduler, 
        device = torch.device("cpu"), 
    ):
        self.fit_loaders, self.num_epochs,  = fit_loaders, num_epochs, 
        self.client_model = client_model
        self.optimizer = optimizer
        self.lr_scheduler = lr_scheduler
        self.device = device

        self.client_model = self.client_model.to(self.device)
        self.round = 1

    def get_parameters(self, 
        config, 
    ):
        parameters = [value.cpu().numpy() for key, value in self.client_model.state_dict().items()]

        return parameters

    def set_parameters(self, 
        parameters, 
    ):
        keys = [key for key in self.client_model.state_dict().keys()]
        self.client_model.load_state_dict(
            collections.OrderedDict({key:torch.tensor(value) for key, value in zip(keys, parameters)}), 
            strict = False, 
        )
    def fit(self, 
        parameters, config, 
    ):
        self.set_parameters(parameters)
        self.client_model.train()
        if self.round > 1:
            self.communication_tok = time.time()
            wandb.log({"communication_time":self.communication_tok - self.communication_tik}, step = self.round)

        self.lr_scheduler.step()
        self.training_tik = time.time()
        results = client_fit_fn(
            self.fit_loaders, self.num_epochs, 
            self.client_model, 
            self.optimizer, 
            self.device, 
        )
        self.training_tok = time.time()
        wandb.log({"training_time":self.training_tok - self.training_tik}, step = self.round)

        self.communication_tik = time.time()
        self.round += 1

        return self.get_parameters({}), len(self.fit_loaders["fit"].dataset), results

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--server_address", type = str, default = "127.0.0.1"), parser.add_argument("--server_port", type = int, default = 9999)
    parser.add_argument("--num_rounds", type = int, default = 500)
    parser.add_argument("--num_clients", type = int, default = 8)
    parser.add_argument("--client_id", type = int)
    parser.add_argument("--dataset", type = str), parser.add_argument("--num_classes", type = int)
    parser.add_argument("--project", type = str)
    args = parser.parse_args()
    wandb.login(key = "3304b9a0c28f65f7d1097ef922eca22b370116cb")
    wandb.init(
        entity = "ods-team", project = args.project, 
        name = "client {}".format(args.client_id), 
    )

    if "MNIST" in args.dataset:
        image_size, num_channels,  = 28, 1, 
    else:
        image_size, num_channels,  = 32, 3, 

    fit_loaders = {
        "fit":torch.utils.data.DataLoader(
            ImageDataset(
                data_dir = "../../../datasets/{}/clients/c{}/fit/".format(args.dataset, args.client_id), 
                image_size = image_size, 
                augment = True, 
            ), 
            batch_size = 16, 
            shuffle = True, 
        ), 
        "evaluate":torch.utils.data.DataLoader(
            ImageDataset(
                data_dir = "../../../datasets/{}/clients/c{}/evaluate/".format(args.dataset, args.client_id), 
                image_size = image_size, 
                augment = False, 
            ), 
            batch_size = 16, 
            shuffle = False, 
        ), 
    }
    client_model = torchvision.models.resnet18()
    client_model.fc = nn.Linear(
        client_model.fc.in_features, args.num_classes, 
    )
    optimizer = optim.SGD(
        client_model.parameters(), weight_decay = 1e-4, 
        lr = 0.01, 
    )

    lr_scheduler = optim.lr_scheduler.CosineAnnealingLR(
        optimizer, 
        T_max = args.num_rounds, 
    )
    client = Client(
        fit_loaders, num_epochs = 2, 
        client_model = client_model, 
        optimizer = optimizer, 
        lr_scheduler = lr_scheduler, 
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu"), 
    )
    fl.client.start_numpy_client(
        server_address = "{}:{}".format(args.server_address, args.server_port), 
        client = client, 
    )