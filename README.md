# Odoo email processor for Cloudflare Email Workers

This script below can be used to enable a Cloudflare Email Worker to forward inbound emails to your self-hosted Odoo instance. It might work for hosted Odoo as well - who knows?

## Variables

You must set the following Variables to talk to your instance:

 - `ODOO_DATABASE` (eg the Odoo database)
 - `ODOO_USERID` (for the user - try `2`)
 - `ODOO_PASSWORD` (the password for that user ID)
 - `ODOO_HOST` (the host eg `crm.example.com`)
 - `ODOO_PORT` (the port, hopefully `443`)
 - `ODOO_PROTOCOL` (the protocol, hopefully `https`)

## Using

Once you have set it all up - point the "catch-all" for the domain at this email worker.

Good luck!

<img width="1285" alt="CreateWorker" src="https://user-images.githubusercontent.com/4564803/220290816-3c53bccc-a9d7-4436-ba8b-661f24e9ad57.png">

<img width="1008" alt="CreateMyOwn" src="https://user-images.githubusercontent.com/4564803/220291035-61effe54-a1a2-4bfe-ac63-09acc4f834fe.png">

<img width="923" alt="AddCode" src="https://user-images.githubusercontent.com/4564803/220291501-b67ca475-55ed-450d-a318-4164a82fa1f4.png">

<img width="1310" alt="AddVariables" src="https://user-images.githubusercontent.com/4564803/220291544-9be4232c-8707-48ba-bd4d-36ebe40ef61b.png">