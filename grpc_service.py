async def InitiateFileUpload(self, request, context):
    """Iniciar upload de arquivo"""
    try:
        result = await self.storage_service.initiate_upload(
            file_name=request.filename,
            file_size=request.file_size,
            conversation_id=request.conversation_id
        )
        
        return InitFileUploadResponse(
            upload_id=result['upload_id'],
            file_id=result['file_id'],
            chunk_size=result['chunk_size'],
            expires_in=result['expires_in']
        )
    except Exception as e:
        await context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(e))

async def UploadFileChunk(self, request_iterator, context):
    """Upload chunk do arquivo"""
    chunks_info = []
    
    async for chunk in request_iterator:
        try:
            result = await self.storage_service.upload_chunk(
                upload_id=chunk.upload_id,
                chunk_number=chunk.chunk_number,
                chunk_data=chunk.data,
                total_chunks=chunk.total_chunks
            )
            
            chunks_info.append(result)
            
            yield FileChunkAck(
                success=True,
                checksum=result['checksum']
            )
        except Exception as e:
            logger.error(f"Erro no upload de chunk: {e}")
            await context.abort(grpc.StatusCode.INTERNAL, str(e))

async def CompleteFileUpload(self, request, context):
    """Finalizar upload"""
    try:
        result = await self.storage_service.complete_upload(
            upload_id=request.upload_id,
            chunks=[{
                'chunk_number': c.chunk_number,
                'checksum': c.checksum
            } for c in request.chunks],
            metadata={
                'filename': 'file',  # Extrair do upload_id
                'mime_type': 'application/octet-stream',
                'file_size': 0
            }
        )
        
        return CompleteFileUploadResponse(
            file_id=result['file_id'],
            status=result['status'],
            file_size=result['size']
        )
    except Exception as e:
        await context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(e))

async def GetFileDownloadURL(self, request, context):
    """Obter URL presigned para download"""
    try:
        url = await self.storage_service.get_presigned_url(
            file_id=request.file_id,
            expires_in=request.expires_in if request.expires_in > 0 else 3600
        )
        
        return GetFileDownloadURLResponse(
            presigned_url=url,
            expires_in=request.expires_in
        )
    except Exception as e:
        await context.abort(grpc.StatusCode.NOT_FOUND, str(e))
