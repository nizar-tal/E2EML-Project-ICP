Project Description

# Overview

In this project you will implement, evaluate, operate, monitor, and optimize an end-to-end ML pipeline. The details of four kinds of pipelines: datasets, model choices, metrics are provided to you. The specific pipeline that you wish to implement is your choice. 

The focus of the project is to implement the pipeline choices, evaluate which configuration of the pipeline is best and under what data distributions, operationalize the pipelines on the cloud, monitor their real-time behavior, and optimize the choice of a pipeline configuration. 

The project entails many concerns, including deployment, scaling, reliability, drift and feedback loops. It also has three milestones including a final project presentation. 

# Overall mechanics and infrastructure


**Teamwork:** You will work on this project in your assigned teams. As a team, you will use a shared GitHub repository and a virtual machine to coordinate your work. Please establish a way of communication and collaboration that works for your team -- for example, a Teams channel. Please agree on tasks and responsibilities. We expect that team members will have different backgrounds and different amounts of experience with machine learning and engineering -- this is intentional. Use the first milestone to identify strength and weaknesses, fill missing gaps in background knowledge, and teach each other about tools and practices that are effective for this task. Finally, be a good team citizen.

**Milestones:** For each milestone and the final presentation, there are separate deliverables, described below. The milestones are checkpoints to ensure that certain functionality has been delivered. 

Milestones are graded on a pass/fail scheme for the criteria listed with each milestone. A fail turns into a pass if it is achieved by the end of the next milestone. All milestones must be delivered by the final due date. 
Note, Milestones build on each other. We recommend to look at all milestones before starting the project, as you may make different design decision and avoid extensive rework.

**Pipelines:** The schematic for pipelines is here. Each pipeline has input datasets and variety of models for each stage. The SLA for each pipeline is provided at the end of the schematic. 

**Infrastructure:**  We provide *Dockerfiles* for each pipeline use case. The Dockerfile  specifies datasets and models to download. You should build the *Dockerfile* into a container and peruse the data and model files. Further details on how to use the Dockerfile are present in the projects directory.

>You may request more computing resources from the course staff if the virtual machine’s resources are insufficient -- we may or may not be able to accommodate such requests, it may take a few days, and will require a system reboot.

**Data** You do not need to use all provided data. Identify what data is relevant. 
> Shankar add more details once the data are identified. 


**Languages, tools, and frameworks:** Your team is free to chose any technology stack for any part of this project. You have root access to your virtual machine and are free to install any software you deem suitable. You also may use external data and services (e.g. cloud services) as long as you can make them also accessible to the course staff. For example, you can use the free cloud credits that companies like Microsoft, Google, and AWS provide to students for this project. Whenever you set up tools or services, pay some attention to configuring them with reasonable security measures; past student solutions have been actively exploited in past projects and this can lead to data loss or loss of internet access for your virtual machine.

**Documentation** For all milestones, we ask you to discuss some aspects of your design decision and implementation. It may be a good idea to write general documentation that is useful for the team in a place that is shared and accessible to the team (e.g., README.md or wiki pages on GitHub). Conversely it may be a good idea to include text or figures you write for reports as part of the project documentation. Feel free to link to more detailed documentation from your report or simply copy material from existing documentation into the report.

In general, we do not much care about the format or location of where we can find parts of your answers, such as code and screenshots, as long as we can find it. Please make an effort to be clear where to find content if it is not copied directly into the report, preferably with direct links to individual files or even lines


# Milestone 1

### Learning Goals: 
The primary task is to set up multiple pipeline configurations, where in each pipeline configuration provides some result to compare pipelines. Note we do not care about the accuracy of fidelity of the result at this point. At this point we care 
whether a pipe is functional or not. For example, in ID card processing, one pipeline configuration is [red channel, Tesseract, Classification-level-2]. Define the accuracy of this pipeline and compute it.  
    
### Tasks: 

T1. Meet with your team members. For this milestone it may be helpful to work on task individually for a
while, and then get together to create one working notebook that is documented.
Alternatively, you may decide to code up each conguration individually and then merge your
congurations into a single pipeline. In either case, decide how you divide the work (minimum: who is
going to do what and by when). Share team skills and responsibilities.

T2. Setup pipeline congurations in a Jupyter notebook. This is a complex task, which will require you
to connect the input datasets to the rst step of the pipeline, the rst step to the second step, and so
on, and nally output a basic accuracy number for the pipeline. We have provided one accuracy metric,
which can be used as an assertion. It is upto you to think of other improved accuracy metrics and
provide justication for their use. Once you have one single pipeline working, experiment by changing
models at each step and set up as many pipeline congurations as possible.
Run each pipeline conguration and obtain pipeline latency and accuracy. Report as a table for each
conguration

T3. Write a report. In this report describe:

- Write and submit a short report that describes the pipeline, its objective and architecture.
Architecture includes description of datasets, models, and assertions used, and the resulting
pipeline congurations.

- Mention how many choices of datasets and models were used and the number of resulting
pipeline configurations that are possible in your pipeline.

- For each pipeline configuration, report the accuracy (in terms of number of assertions), latency,
and whether SLA was met, as a table. (We will release the SLAs for each pipeline soon.)

- Ensure that your notebook is well-documented starting with the name of the pipeline used, and
report is detailed and understandable.

- Briefly describe in your report how your team organizes itself. What communication channels do
you use? How have you divided the work? Did you encounter any teamwork problems and what
steps are you planning to take in future milestones to avoid them?


### Deliverables.

1.  Submit your Notebook which consists of code for pipeline configurations to GitHub. Provide a Dockerfile of your container including the notebook on your Team GitHub and share with us for grading. Uncle the report on Github as well.
   
### Grading.

This milestone is worth 10 points. 3 points for producing a notebook, 3 points for sharing a Dockerfile that is downloadable,  runnable into a container, and regenerating the results reported in the document. 4 points for the report that is clear, complete, and precise.

