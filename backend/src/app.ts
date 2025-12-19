import express, { Express } from "express";
// import faucet from "./faucet/faucet.routes";

const app: Express = express();

app.use(express.json());

// app.use("/api/faucet", faucet);

export default app;
