# Local models for the director, served by Ollama.
{ pkgs, lib, ... }:

{
  services.ollama = {
    enable = true;
    package = lib.mkDefault pkgs.ollama-cuda;
    environmentVariables = {
      # Store the context cache at 8 bits instead of 16: half the memory, so
      # more context or more of the model fits on the GPU.
      OLLAMA_FLASH_ATTENTION = "1";
      OLLAMA_KV_CACHE_TYPE = "q8_0";
    };
  };
}
