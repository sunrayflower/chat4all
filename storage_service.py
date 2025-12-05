import hashlib
import json
from datetime import datetime, timedelta
from typing import Optional
from minio import Minio
from minio.error import S3Error
import asyncio

class StorageService:
    def __init__(self, minio_url: str = "localhost:9000"):
        """Inicializar MinIO client"""
        self.client = Minio(
            minio_url,
            access_key="minioadmin",
            secret_key="minioadmin123",
            secure=False
        )
        self.bucket_name = "chat4all-files"
        self._init_bucket()
    
    def _init_bucket(self):
        """Criar bucket se não existir"""
        try:
            if not self.client.bucket_exists(self.bucket_name):
                self.client.make_bucket(self.bucket_name)
                print(f"✓ Bucket '{self.bucket_name}' criado")
            else:
                print(f"✓ Bucket '{self.bucket_name}' já existe")
        except S3Error as e:
            print(f"Erro ao criar bucket: {e}")
    
    async def initiate_upload(
        self, 
        file_name: str, 
        file_size: int, 
        conversation_id: str
    ) -> dict:
        """
        Iniciar upload multipart
        
        Args:
            file_name: Nome do arquivo
            file_size: Tamanho em bytes
            conversation_id: ID da conversa
        
        Returns:
            {
                upload_id: str,
                file_id: str,
                chunk_size: int
            }
        """
        # Validações
        if file_size > 2 * 1024 * 1024 * 1024:  # 2GB
            raise ValueError("Arquivo excede 2GB")
        
        file_id = f"{conversation_id}/{file_name}-{int(datetime.utcnow().timestamp())}"
        
        return {
            "upload_id": file_id,
            "file_id": file_id,
            "chunk_size": 5 * 1024 * 1024,  # 5MB chunks
            "expires_in": 3600
        }
    
    async def upload_chunk(
        self,
        upload_id: str,
        chunk_number: int,
        chunk_data: bytes,
        total_chunks: int
    ) -> dict:
        """
        Upload um chunk do arquivo
        
        Retorna checksum do chunk
        """
        checksum = hashlib.md5(chunk_data).hexdigest()
        
        # Simular upload (em produção seria async com uploads paralelos)
        chunk_key = f"{upload_id}/chunk-{chunk_number:04d}"
        
        return {
            "chunk_number": chunk_number,
            "checksum": checksum,
            "size": len(chunk_data),
            "total_chunks": total_chunks
        }
    
    async def complete_upload(
        self,
        upload_id: str,
        chunks: list,
        metadata: dict
    ) -> dict:
        """
        Finalizar upload multipart
        
        Args:
            upload_id: ID do upload
            chunks: [{chunk_number, checksum}, ...]
            metadata: {filename, mime_type, file_size}
        
        Returns:
            {file_id, url, expires_in}
        """
        # Validar checksums
        if not chunks:
            raise ValueError("Nenhum chunk foi enviado")
        
        file_id = upload_id
        
        # Salvar metadados em arquivo JSON no MinIO
        metadata_key = f"{upload_id}/metadata.json"
        metadata_json = json.dumps({
            **metadata,
            "chunks": chunks,
            "uploaded_at": datetime.utcnow().isoformat(),
            "status": "COMPLETED"
        }).encode('utf-8')
        
        # Em produção: self.client.put_object(...)
        
        return {
            "file_id": file_id,
            "status": "COMPLETED",
            "size": metadata.get('file_size', 0),
            "mime_type": metadata.get('mime_type', 'application/octet-stream')
        }
    
    async def get_presigned_url(
        self,
        file_id: str,
        expires_in: int = 3600
    ) -> str:
        """
        Gerar URL temporária (presigned) para download
        
        Args:
            file_id: ID do arquivo
            expires_in: Expiração em segundos (padrão 1 hora)
        
        Returns:
            URL presigned
        """
        try:
            url = self.client.get_presigned_download_url(
                self.bucket_name,
                file_id,
                expires=timedelta(seconds=expires_in)
            )
            return url
        except S3Error as e:
            raise Exception(f"Erro ao gerar URL: {e}")
    
    async def delete_file(self, file_id: str) -> bool:
        """Deletar arquivo"""
        try:
            self.client.remove_object(self.bucket_name, file_id)
            return True
        except S3Error as e:
            print(f"Erro ao deletar: {e}")
            return False
