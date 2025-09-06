A self hosted k8s system for homelab
====================================

Initial Conifiguration
-----------------------

Install Ubuntu over network boot with ssh enable, configure the switch ant 2 Nics, one ofr longhorn data plan and one for k3d / control plane. 
Set up partitioning and the initial k8s cluster.

Ansible
-------

Some/most of the OS configuration should be done trough ansible so we can keep it up to date. Set up basic scaolding to be able to run it.

Tuning
------

Mesure power usage, tune the OS for the odroid, make sure hdds are spinend down etc.

Gitops Setup
------------

I want to have either a branch or a separate repo where I will store config, and the K8s resources. I want to have a process where I can use helm or kustomize to render the manifests and use ArgoCD to sync it to the cluster. ArgoCD will ahve to be part of genesis of the clsuter.  

Recovery mode
--------------

I want to have a way to pre-configure  a node by mac to boot in recovery mode, this will skip some of the regular config and instead start an ssh server and report back to the genesis server when ssh is ready to connect and the IP address of it. 

Ingest
-------

I want to have https with my domain configured so I can expose some of my k8s services. 
Will also have to configure my microtic firewall to work with this. 

Storage
--------

Each node will have 2 NICs, one of them for the control plane and ingress and the other exclusive for storage. Volumes will be managed by longhorn and part of the config. The HDDs and remaining SSD space needs to be used up by longhorn, tagged differently so apps can choose if they want to be on HDD or SSD and have their own replication stragey. Longhor can be deployed using ARGO. 

First service
-------------

I want to have some first service running, maybe just a hello world static website.

Updates
-------

Use digests to fix all docker images and other packages used. Set up some way, e.g. local renovate runs to update all packages. 
